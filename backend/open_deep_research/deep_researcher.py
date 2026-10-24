"""Main LangGraph implementation for the Deep Research agent with TOON optimization."""

import asyncio
import json
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    filter_messages,
    get_buffer_string,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .configuration import (
    Configuration,
    SearchAPI,
)
from .prompts import (
    clarify_with_user_instructions,
    compress_research_simple_human_message,
    compress_research_system_prompt,
    final_report_generation_prompt,
    lead_researcher_prompt,
    research_system_prompt,
    transform_messages_into_research_topic_prompt,
)
from .state import (
    AgentInputState,
    AgentState,
    ClarifyWithUser,
    ConductResearch,
    ResearchComplete,
    ResearcherOutputState,
    ResearcherState,
    ResearchQuestion,
    SupervisorState,
)
from .utils import (
    anthropic_websearch_called,
    get_all_tools,
    get_api_key_for_model,
    get_configured_chat_model,
    get_model_token_limit,
    get_notes_from_tool_calls,
    get_today_str,
    is_token_limit_exceeded,
    openai_websearch_called,
    remove_up_to_last_ai_message,
    think_tool,
)
from typing import Optional
import fitz 
import base64
import tiktoken
import boto3
import uuid
import json
from .db_chroma import get_user_summaries, save_summary
import mimetypes
from langchain_core.prompts import ChatPromptTemplate
from groq import AsyncGroq
import os
from dotenv import load_dotenv
from .data_extractor import extract_data
from datetime import datetime, date
import traceback

load_dotenv()
groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip()

if not groq_api_key:
    raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")

client = AsyncGroq(api_key=groq_api_key)
MODEL_NAME = "openai/gpt-oss-120b"

# Initialize a configurable model that we will use throughout the agent
configurable_model = init_chat_model(
    configurable_fields=("model", "max_tokens", "api_key"),
)

async def clarify_with_user(state: AgentState, config: RunnableConfig) -> Command[Literal["write_research_brief", "__end__"]]:
    """Analyze user messages and ask clarifying questions if the research scope is unclear.
    
    This function determines whether the user's request needs clarification before proceeding
    with research. If clarification is disabled or not needed, it proceeds directly to research.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings and preferences
        
    Returns:
        Command to either end with a clarifying question or proceed to research brief
    """
    # Step 1: Check if clarification is enabled in configuration
    configurable = Configuration.from_runnable_config(config)
    if not configurable.allow_clarification:
        # Skip clarification step and proceed directly to research
        return Command(goto="write_research_brief")
    
    # Step 2: Prepare the model for structured clarification analysis
    messages = state["messages"]
    model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Configure model with structured output and retry logic
    clarification_model = (
        configurable_model
        .with_structured_output(ClarifyWithUser)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(model_config)
    )
    
    # Step 3: Analyze whether clarification is needed
    prompt_content = clarify_with_user_instructions.format(
        messages=get_buffer_string(messages), 
        date=get_today_str()
    )
    response = await clarification_model.ainvoke([HumanMessage(content=prompt_content)])
    
    # Step 4: Route based on clarification analysis
    if response.need_clarification:
        # End with clarifying question for user
        return Command(
            goto=END, 
            update={"messages": [AIMessage(content=response.question)]}
        )
    else:
        # Proceed to research with verification message
        return Command(
            goto="write_research_brief", 
            update={"messages": [AIMessage(content=response.verification)]}
        )

async def write_research_brief(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor"]]:
    """Transform user messages into a structured research brief and initialize supervisor.
    
    This function analyzes the user's messages and generates a focused research brief
    that will guide the research supervisor. It also sets up the initial supervisor
    context with appropriate prompts and instructions.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to research supervisor with initialized context
    """
    # Step 1: Set up the research model
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Groq can reject forced structured-output tool calls for long prompts.
    research_model = configurable_model.with_config(research_model_config)
    
    # Step 2: Generate structured research brief from user messages
    prompt_content = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(state.get("messages", [])),
        date=get_today_str()
    )
    response = await research_model.ainvoke([HumanMessage(content=prompt_content)])
    research_brief = response.content if isinstance(response.content, str) else str(response.content)
    
    # Step 3: Extract report_date from state (added by run_researcher_from_data)
    report_date = state.get("report_date") or datetime.now().strftime("%Y-%m-%d")
    
    # Step 4: Initialize supervisor with research brief and instructions
    supervisor_system_prompt = lead_researcher_prompt.format(
        date=get_today_str(),
        report_date=report_date,  # ADD THIS
        max_concurrent_research_units=configurable.max_concurrent_research_units,
        max_researcher_iterations=configurable.max_researcher_iterations
    )
    
    return Command(
        goto="research_supervisor", 
        update={
            "research_brief": research_brief,
            "supervisor_messages": {
                "type": "override",
                "value": [
                    SystemMessage(content=supervisor_system_prompt),
                    HumanMessage(content=research_brief)
                ]
            }
        }
    )

async def supervisor(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor_tools"]]:
    """Lead research supervisor that plans research strategy and delegates to researchers.
    
    The supervisor analyzes the research brief and decides how to break down the research
    into manageable tasks. It can use think_tool for strategic planning, ConductResearch
    to delegate tasks to sub-researchers, or ResearchComplete when satisfied with findings.
    
    Args:
        state: Current supervisor state with messages and research context
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to supervisor_tools for tool execution
    """
    # Step 1: Configure the supervisor model with available tools
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Available tools: research delegation, completion signaling, and strategic thinking
    lead_researcher_tools = [ConductResearch, ResearchComplete, think_tool]
    
    # Configure model with tools, retry logic, and model settings
    research_model = (
        configurable_model
        .bind_tools(lead_researcher_tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 2: Generate supervisor response based on current context
    supervisor_messages = state.get("supervisor_messages", [])
    response = await research_model.ainvoke(supervisor_messages)
    
    # Step 3: Update state and proceed to tool execution
    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def supervisor_tools(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor", "__end__"]]:
    """Execute tools called by the supervisor, including research delegation and strategic thinking.
    
    This function handles three types of supervisor tool calls:
    1. think_tool - Strategic reflection that continues the conversation
    2. ConductResearch - Delegates research tasks to sub-researchers
    3. ResearchComplete - Signals completion of research phase
    
    Args:
        state: Current supervisor state with messages and iteration count
        config: Runtime configuration with research limits and model settings
        
    Returns:
        Command to either continue supervision loop or end research phase
    """
    # Step 1: Extract current state and check exit conditions
    configurable = Configuration.from_runnable_config(config)
    supervisor_messages = state.get("supervisor_messages", [])
    research_iterations = state.get("research_iterations", 0)
    most_recent_message = supervisor_messages[-1]
    
    # Early exit if no search API is configured (skip all research)
    if configurable.search_api == SearchAPI.NONE:
        return Command(
            goto=END,
            update={
                "notes": ["Direct analysis without external research due to minimal token configuration"],
                "research_brief": state.get("research_brief", "")
            }
        )
    
    # Define exit criteria for research phase
    exceeded_allowed_iterations = research_iterations > configurable.max_researcher_iterations
    no_tool_calls = not most_recent_message.tool_calls
    research_complete_tool_call = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    # Exit if any termination condition is met
    if exceeded_allowed_iterations or no_tool_calls or research_complete_tool_call:
        return Command(
            goto=END,
            update={
                "notes": get_notes_from_tool_calls(supervisor_messages),
                "research_brief": state.get("research_brief", "")
            }
        )
    
    # Step 2: Process all tool calls together (both think_tool and ConductResearch)
    all_tool_messages = []
    update_payload = {"supervisor_messages": []}
    
    # Handle think_tool calls (strategic reflection)
    think_tool_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "think_tool"
    ]
    
    for tool_call in think_tool_calls:
        reflection_content = tool_call["args"]["reflection"]
        all_tool_messages.append(ToolMessage(
            content=f"Reflection recorded: {reflection_content}",
            name="think_tool",
            tool_call_id=tool_call["id"]
        ))
    
    # Handle ConductResearch calls (research delegation)
    conduct_research_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "ConductResearch"
    ]
    
    if conduct_research_calls:
        try:
            # Limit concurrent research units to prevent resource exhaustion
            allowed_conduct_research_calls = conduct_research_calls[:configurable.max_concurrent_research_units]
            overflow_conduct_research_calls = conduct_research_calls[configurable.max_concurrent_research_units:]
            
            # Execute research tasks in parallel
            research_tasks = [
                researcher_subgraph.ainvoke({
                    "researcher_messages": [
                        HumanMessage(content=tool_call["args"]["research_topic"])
                    ],
                    "research_topic": tool_call["args"]["research_topic"]
                }, config) 
                for tool_call in allowed_conduct_research_calls
            ]
            
            tool_results = await asyncio.gather(*research_tasks)
            
            # Create tool messages with research results
            for observation, tool_call in zip(tool_results, allowed_conduct_research_calls):
                all_tool_messages.append(ToolMessage(
                    content=observation.get("compressed_research", "Error synthesizing research report: Maximum retries exceeded"),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"]
                ))
            
            # Handle overflow research calls with error messages
            for overflow_call in overflow_conduct_research_calls:
                all_tool_messages.append(ToolMessage(
                    content=f"Error: Did not run this research as you have already exceeded the maximum number of concurrent research units. Please try again with {configurable.max_concurrent_research_units} or fewer research units.",
                    name="ConductResearch",
                    tool_call_id=overflow_call["id"]
                ))
            
            # Aggregate raw notes from all research results
            raw_notes_concat = "\n".join([
                "\n".join(observation.get("raw_notes", [])) 
                for observation in tool_results
            ])
            
            if raw_notes_concat:
                update_payload["raw_notes"] = [raw_notes_concat]
                
        except Exception as e:
            # Handle research execution errors
            if is_token_limit_exceeded(e, configurable.research_model) or True:
                # Token limit exceeded or other error - end research phase
                return Command(
                    goto=END,
                    update={
                        "notes": get_notes_from_tool_calls(supervisor_messages),
                        "research_brief": state.get("research_brief", "")
                    }
                )
    
    # Step 3: Return command with all tool results
    update_payload["supervisor_messages"] = all_tool_messages
    return Command(
        goto="supervisor",
        update=update_payload
    ) 

# Supervisor Subgraph Construction
# Creates the supervisor workflow that manages research delegation and coordination
supervisor_builder = StateGraph(SupervisorState, context_schema=Configuration)

# Add supervisor nodes for research management
supervisor_builder.add_node("supervisor", supervisor)           # Main supervisor logic
supervisor_builder.add_node("supervisor_tools", supervisor_tools)  # Tool execution handler

# Define supervisor workflow edges
supervisor_builder.add_edge(START, "supervisor")  # Entry point to supervisor

# Compile supervisor subgraph for use in main workflow
supervisor_subgraph = supervisor_builder.compile()

async def researcher(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher_tools"]]:
    """Individual researcher that conducts focused research on specific topics.
    
    This researcher is given a specific research topic by the supervisor and uses
    available tools (search, think_tool, MCP tools) to gather comprehensive information.
    It can use think_tool for strategic planning between searches.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all available research tools (search, MCP, think_tool)
    tools = await get_all_tools(config)
    if len(tools) == 0 or configurable.search_api == SearchAPI.NONE:
        # No tools available or search disabled - provide direct analysis
        return Command(
            goto="compress_research",
            update={
                "researcher_messages": [AIMessage(content="Direct analysis based on provided data without external research due to minimal configuration.")]
            }
        )
    
    # Step 2: Configure the researcher model with tools
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Prepare system prompt with MCP context if available
    researcher_prompt = research_system_prompt.format(
        mcp_prompt=configurable.mcp_prompt or "", 
        date=get_today_str()
    )
    
    # Configure model with tools, retry logic, and settings
    research_model = (
        configurable_model
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 3: Generate researcher response with system context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    response = await research_model.ainvoke(messages)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1
        }
    )

# Tool Execution Helper Function
async def execute_tool_safely(tool, args, config):
    """Safely execute a tool with error handling."""
    try:
        return await tool.ainvoke(args, config)
    except Exception as e:
        return f"Error executing tool: {str(e)}"

async def researcher_tools(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher", "compress_research"]]:
    """Execute tools called by the researcher, including search tools and strategic thinking.
    
    This function handles various types of researcher tool calls:
    1. think_tool - Strategic reflection that continues the research conversation
    2. Search tools (tavily_search, web_search) - Information gathering
    3. MCP tools - External tool integrations
    4. ResearchComplete - Signals completion of individual research task
    
    Args:
        state: Current researcher state with messages and iteration count
        config: Runtime configuration with research limits and tool settings
        
    Returns:
        Command to either continue research loop or proceed to compression
    """
    # Step 1: Extract current state and check early exit conditions
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    most_recent_message = researcher_messages[-1]
    
    # Early exit if no tool calls were made (including native web search)
    has_tool_calls = bool(most_recent_message.tool_calls)
    has_native_search = (
        openai_websearch_called(most_recent_message) or 
        anthropic_websearch_called(most_recent_message)
    )
    
    if not has_tool_calls and not has_native_search:
        return Command(goto="compress_research")
    
    # Step 2: Handle other tool calls (search, MCP tools, etc.)
    tools = await get_all_tools(config)
    tools_by_name = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search"): tool 
        for tool in tools
    }
    
    # Execute all tool calls in parallel
    tool_calls = most_recent_message.tool_calls
    tool_execution_tasks = [
        execute_tool_safely(tools_by_name[tool_call["name"]], tool_call["args"], config) 
        for tool_call in tool_calls
    ]
    observations = await asyncio.gather(*tool_execution_tasks)
    
    # Create tool messages from execution results
    tool_outputs = [
        ToolMessage(
            content=observation,
            name=tool_call["name"],
            tool_call_id=tool_call["id"]
        ) 
        for observation, tool_call in zip(observations, tool_calls)
    ]
    
    # Step 3: Check late exit conditions (after processing tools)
    exceeded_iterations = state.get("tool_call_iterations", 0) >= configurable.max_react_tool_calls
    research_complete_called = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    if exceeded_iterations or research_complete_called:
        # End research and proceed to compression
        return Command(
            goto="compress_research",
            update={"researcher_messages": tool_outputs}
        )
    
    # Continue research loop with tool results
    return Command(
        goto="researcher",
        update={"researcher_messages": tool_outputs}
    )

async def compress_research(state: ResearcherState, config: RunnableConfig):
    """Compress and synthesize research findings into a concise, structured summary.
    
    This function takes all the research findings, tool outputs, and AI messages from
    a researcher's work and distills them into a clean, comprehensive summary while
    preserving all important information and findings.
    
    Args:
        state: Current researcher state with accumulated research messages
        config: Runtime configuration with compression model settings
        
    Returns:
        Dictionary containing compressed research summary and raw notes
    """
    # Step 1: Configure the compression model
    configurable = Configuration.from_runnable_config(config)
    synthesizer_model = configurable_model.with_config({
        "model": configurable.compression_model,
        "max_tokens": configurable.compression_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.compression_model, config),
        "tags": ["langsmith:nostream"]
    })
    
    # Step 2: Prepare messages for compression
    researcher_messages = state.get("researcher_messages", [])
    
    # Add instruction to switch from research mode to compression mode
    researcher_messages.append(HumanMessage(content=compress_research_simple_human_message))
    
    # Step 3: Attempt compression with retry logic for token limit issues
    synthesis_attempts = 0
    max_attempts = 1  # Reduced to 1 for minimal token usage
    
    while synthesis_attempts < max_attempts:
        try:
            # Create system prompt focused on compression task
            compression_prompt = compress_research_system_prompt.format(date=get_today_str())
            messages = [SystemMessage(content=compression_prompt)] + researcher_messages
            
            # Execute compression
            response = await synthesizer_model.ainvoke(messages)
            
            # Extract raw notes from all tool and AI messages
            raw_notes_content = "\n".join([
                str(message.content) 
                for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
            ])
            
            # Return successful compression result
            return {
                "compressed_research": str(response.content),
                "raw_notes": [raw_notes_content]
            }
            
        except Exception as e:
            synthesis_attempts += 1
            
            # Handle token limit exceeded by removing older messages
            if is_token_limit_exceeded(e, configurable.research_model):
                researcher_messages = remove_up_to_last_ai_message(researcher_messages)
                continue
            
            # For other errors, continue retrying
            continue
    
    # Step 4: Return error result if all attempts failed
    raw_notes_content = "\n".join([
        str(message.content) 
        for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
    ])
    
    return {
        "compressed_research": "Error synthesizing research report: Maximum retries exceeded",
        "raw_notes": [raw_notes_content]
    }

# Researcher Subgraph Construction
# Creates individual researcher workflow for conducting focused research on specific topics
researcher_builder = StateGraph(
    ResearcherState, 
    output_schema=ResearcherOutputState, 
    context_schema=Configuration
)

# Add researcher nodes for research execution and compression
researcher_builder.add_node("researcher", researcher)                 # Main researcher logic
researcher_builder.add_node("researcher_tools", researcher_tools)     # Tool execution handler
researcher_builder.add_node("compress_research", compress_research)   # Research compression

# Define researcher workflow edges
researcher_builder.add_edge(START, "researcher")           # Entry point to researcher
researcher_builder.add_edge("compress_research", END)      # Exit point after compression

# Compile researcher subgraph for parallel execution by supervisor
researcher_subgraph = researcher_builder.compile()

async def final_report_generation(state: AgentState, config: RunnableConfig):
    """Generate the final comprehensive research report with retry logic for token limits.
    
    This function takes all collected research findings and synthesizes them into a 
    well-structured, comprehensive final report using the configured report generation model.
    
    Args:
        state: Agent state containing research findings and context
        config: Runtime configuration with model settings and API keys
        
    Returns:
        Dictionary containing the final report and cleared state
    """
    # Step 1: Extract research findings and prepare state cleanup
    notes = state.get("notes", [])
    cleared_state = {"notes": {"type": "override", "value": []}}
    findings = "\n".join(notes)
    
    # Step 2: Configure the final report generation model
    configurable = Configuration.from_runnable_config(config)
    writer_model_config = {
        "model": configurable.final_report_model,
        "max_tokens": 1200,
        "api_key": get_api_key_for_model(configurable.final_report_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Retrieve user_id and report_date from state
    user_id = state.get("user_id", None)
    report_date = state.get("report_date") or datetime.now().strftime("%Y-%m-%d")  # ADD THIS
    previous_summary_context = ""

    if user_id:
        try:
            previous_summaries = get_user_summaries(user_id)
            if previous_summaries:
                # TOON Optimization: Limit to last 3 summaries and truncate each to 100 chars
                recent_summaries = previous_summaries[-3:]
                previous_summary_context = "; ".join(
                    [
                        f"{item.get('date', 'N/A')}: {item.get('summary', '')[:100]}"
                        for item in recent_summaries
                    ]
                )
            else:
                previous_summary_context = "No previous summaries"
        except Exception as e:
            previous_summary_context = f"Error: {str(e)[:50]}"
    
    # Step 3: Attempt report generation with token limit retry logic
    max_retries = 1  # Reduced to 1 for minimal token usage
    current_retry = 0
    findings_token_limit = None
    
    while current_retry <= max_retries:
        try:
            # Determine if this is a follow-up report explicitly
            is_followup = bool(previous_summaries) and len(previous_summaries) > 0
            report_type_explicit = "FOLLOW-UP REPORT" if is_followup else "FIRST-TIME REPORT"
            
            # Keep the final Groq request below the account's 8,000 TPM limit.
            final_report_prompt = f"""Write a concise patient-friendly medical lab report.
Report type: {report_type_explicit}. Report date: {report_date}.
Use only the current lab values below. Mention abnormal values first, practical next steps,
and when urgent medical review is needed. Include a brief baseline/trend statement and this
disclaimer: This information is educational and does not replace a qualified doctor.
Language: {state.get('language_instruction', '')[:120]}.

CURRENT LAB DATA:
{state.get('current_summary_context', '')[:3500]}

RESEARCH FINDINGS:
{findings[:3500]}
"""
            
            # Generate the final report
            final_report = await configurable_model.with_config(writer_model_config).ainvoke([
                HumanMessage(content=final_report_prompt)
            ])
            
            # Return successful report generation
            return {
                "final_report": final_report.content, 
                "messages": [final_report],
                **cleared_state
            }
            
        except Exception as e:
            # Handle token limit exceeded errors with progressive truncation
            if is_token_limit_exceeded(e, configurable.final_report_model):
                current_retry += 1
                
                if current_retry == 1:
                    # First retry: determine initial truncation limit
                    model_token_limit = get_model_token_limit(configurable.final_report_model)
                    if not model_token_limit:
                        return {
                            "final_report": f"Error generating final report: Token limit exceeded, however, we could not determine the model's maximum context length. Please update the model map in deep_researcher/utils.py with this information. {e}",
                            "messages": [AIMessage(content="Report generation failed due to token limits")],
                            **cleared_state
                        }
                    # Use 4x token limit as character approximation for truncation
                    findings_token_limit = model_token_limit * 4
                else:
                    # Subsequent retries: reduce by 10% each time
                    findings_token_limit = int(findings_token_limit * 0.9)
                
                # Truncate findings and retry
                findings = findings[:findings_token_limit]
                continue
            else:
                # Non-token-limit error: return error immediately
                return {
                    "final_report": f"Error generating final report: {e}",
                    "messages": [AIMessage(content="Report generation failed due to an error")],
                    **cleared_state
                }
    
    # Step 4: Return failure result if all retries exhausted
    return {
        "final_report": "Error generating final report: Maximum retries exceeded",
        "messages": [AIMessage(content="Report generation failed after maximum retries")],
        **cleared_state
    }

# Main Deep Researcher Graph Construction
# Creates the complete deep research workflow from user input to final report
deep_researcher_builder = StateGraph(
    AgentState, 
    input_schema=AgentInputState, 
    context_schema=Configuration
)

# Add main workflow nodes for the complete research process
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)           # User clarification phase
deep_researcher_builder.add_node("write_research_brief", write_research_brief)     # Research planning phase
deep_researcher_builder.add_node("research_supervisor", supervisor_subgraph)       # Research execution phase
deep_researcher_builder.add_node("final_report_generation", final_report_generation)  # Report generation phase

# Define main workflow edges for sequential execution
deep_researcher_builder.add_edge(START, "clarify_with_user")                       # Entry point
deep_researcher_builder.add_edge("research_supervisor", "final_report_generation") # Research to report
deep_researcher_builder.add_edge("final_report_generation", END)                   # Final exit point

# Compile the complete deep researcher workflow
deep_researcher = deep_researcher_builder.compile()

s3 = boto3.client("s3")

# Parameter normal ranges for classification
PARAMETER_RANGES = {
            "hdl": {"normal_range": (40, 60)},             
            "ldl": {"normal_range": (0, 100)},              
            "triglycerides": {"normal_range": (0, 150)},   
            "cholesterol": {"normal_range": (125, 200)},
            "hdlldl_ratio": {"normal_range": (0.3, 0.5)},         
            "ldl": {"normal_range": (0, 100)},              
            "ldlhdl_ratio": {"normal_range": (0, 3.5)},           
            "non_hdl_cholesterol": {"normal_range": (0, 130)},      
            "cholesterolhdl_ratio": {"normal_range": (0, 5)},               
            "vldl": {"normal_range": (5, 40)},  
            "troponin_i_level": {"normal_range": (0, 0.04)},       
            "btype_natriuretic_peptide_bnp": {"normal_range": (0, 100)},            
            "c_reactive_protein": {"normal_range": (0, 3)},
            "apolipoprotein_a1": {"normal_range": (120, 160)},     
            "apolipoprotein_b": {"normal_range": (60, 120)},      
            "high_sensitivity_c__reactive_protein": {"normal_range": (0, 3)},                    
            "lipoproteinassociated_phospholipase_a2_lppla2": {"normal_range": (0, 30)},
            "anti_cyclic_citrullinated_peptide_antibody_anti_ccp": {"normal_range": (0, 5)},           
            "anaantinuclear_antibody": {"normal_range": (0, 1)},                
            "homocysteine": {"normal_range": (5, 15)},    
            "fasting_blood_sugar": {"normal_range": (70, 110)},
            "post_prandial_sugar": {"normal_range": (70, 140)},    
            "oxygen_saturation": {"normal_range": (95, 100)},
            "vitamin_b12": {"normal_range": (200, 900)},        
            "folate": {"normal_range": (3, 17)},     
            "t3": {"normal_range": (0.8, 2.0)},     
            "t4": {"normal_range": (5.0, 12.0)},      
            "tsh": {"normal_range": (0.4, 4.0)},
            "free_t3": {"normal_range": (2.3, 4.2)},    
            "free_t4": {"normal_range": (0.8, 1.8)},      
            "antithyroid_peroxidase_antibody_antitpo": {"normal_range": (0, 35)}, 
            "sgpt": {"normal_range": (7, 56)},  
            "sgot": {"normal_range": (10, 40)},
            "transferrin_saturation": {"normal_range": (20, 50)}, 
            "iron": {"normal_range": (50, 170)},                   
            "total_iron_binding_capacity_tibc": {"normal_range": (240, 450)},                  
            "uibc": {"normal_range": (150, 375)},
            "ag_ratio": {"normal_range": (1.0, 2.5)},         
            "alkaline_phosphatase": {"normal_range": (44, 147)},   
            "direct_bilirubin": {"normal_range": (0, 0.3)},         
            "indirect_bilirubin": {"normal_range": (0.2, 0.8)},    
            "total_bilirubin": {"normal_range": (0.3, 1.2)},      
            "gamma_gt": {"normal_range": (0, 51)},                     
            "sgot_sgpt_ratio": {"normal_range": (0.7, 1.5)},      
            "total_protein": {"normal_range": (6, 8.3)},            
            "serum_albumin": {"normal_range": (3.5, 5.0)},         
            "serum_globulin": {"normal_range": (2, 3.5)},          
            "sgot": {"normal_range": (10, 40)},                     
            "sgpt": {"normal_range": (7, 56)},
            "copper": {"normal_range": (70, 140)}, 
            "serum_zinc": {"normal_range": (70, 120)},                  
            "creatinine": {"normal_range": (0.6, 1.3)}, 
            "blood_urea_nitrogen": {"normal_range": (7, 20)},
            "bun_screat_ratio": {"normal_range": (10, 20)},    
            "calcium": {"normal_range": (8.5, 10.2)},               
            "urea_creat_ratio": {"normal_range": (10, 20)},  
            "urea": {"normal_range": (7, 20)},         
            "uric_acid": {"normal_range": (3.5, 7.2)},
            "chlorides": {"normal_range": (96, 106)}, 
            "sodium": {"normal_range": (135, 145)},
            "cystatin_c": {"normal_range": (0.6, 1.2)},                        
            "calprotectin": {"normal_range": (0, 50)},   
            "psa_prostate_specific_antigen": {"normal_range": (0, 4)},       
            "free_prostate_specific_antigen": {"normal_range": (0, 1.5)},    
            "testosterone": {"normal_range": (300, 1000)},
            "estradiol": {"normal_range": (50, 350)},       
            "progesterone": {"normal_range": (5, 20)},       
            "follicle_stimulating_hormone_fsh": {"normal_range": (4.7, 21.5)},            
            "luteinizing_hormone_lh_icsh": {"normal_range": (5, 20)},                 
            "prolactin": {"normal_range": (4, 23)},          
            "antimullerian_hormone": {"normal_range": (1, 4)},      
            "helicobacter_pylori_antigen": {"normal_range": (0, 1)},  
            "amylase": {"normal_range": (30, 110)},
            "lipase": {"normal_range": (0, 160)}, 
            "blood_ketone_d3hb": {"normal_range": (0, 0.6)},   
            "fructosamine": {"normal_range": (200, 285)},  
            "hba1c": {"normal_range": (4, 5.6)},          
            "insulin_serum_fasting": {"normal_range": (2, 25)},           
}

def classify_parameter_status(param_name: str, value: str, normal_range_str: str = None) -> str:
    """
    Classify a parameter as abnormal or normal based on provided or predefined ranges.
    
    Args:
        param_name: Name of the parameter
        value: Current value as string
        normal_range_str: Optional range string like "40 - 60" or "0.1 - 200" from input
        
    Returns: 'abnormal', 'normal', or 'unknown'
    """
    try:
        # Extract numeric value from string (handle formats like "108 mg/dL", "10.8%", etc.)
        value_str = str(value).replace(",", "").strip()
        import re
        match = re.search(r'(\d+\.?\d*)', value_str)
        if not match:
            return "unknown"
        
        numeric_value = float(match.group(1))
        
        # PRIORITY 1: Use provided normalRange from input if available
        if normal_range_str:
            try:
                # Parse range string like "40 - 60" or "0.1 - 200"
                range_match = re.search(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', normal_range_str)
                if range_match:
                    min_val = float(range_match.group(1))
                    max_val = float(range_match.group(2))
                    
                    if min_val <= numeric_value <= max_val:
                        status = "normal"
                    else:
                        status = "abnormal"
                    
                    print(f"[CLASSIFY] {param_name}={numeric_value} | Input Range: [{min_val}, {max_val}] | Status: {status.upper()}")
                    return status
            except Exception as e:
                print(f"[CLASSIFY] Failed to parse normalRange '{normal_range_str}': {e}, falling back to predefined ranges")
        
        # PRIORITY 2: Fall back to predefined ranges if no input range provided
        param_key = (param_name.lower()
                     .replace(" ", "_")
                     .replace("-", "_")
                     .replace(".", "")
                     .replace("(", "")
                     .replace(")", "")
                     .replace(",", ""))
        
        possible_keys = [
            param_key,
            param_key.replace("_", ""),
            param_key.replace("serum_", ""),
            param_key.replace("blood_", ""),
            param_key.replace("total_", ""),
            param_key.replace("_count", ""),
            param_key.replace("ultrasensitive", ""),
            "cholesterol" if "cholesterol" in param_key and "hdl" not in param_key and "ldl" not in param_key else param_key,
            "triglycerides" if "triglyceride" in param_key else param_key,
        ]
        
        # Find matching range
        normal_range = None
        matched_key = None
        for key in possible_keys:
            if key in PARAMETER_RANGES:
                param_config = PARAMETER_RANGES[key]
                if isinstance(param_config, dict) and "normal_range" in param_config:
                    normal_range = param_config["normal_range"]
                    matched_key = key
                    break
                elif isinstance(param_config, tuple):
                    normal_range = param_config
                    matched_key = key
                    break
        
        if not normal_range:
            return "unknown"
        
        if not isinstance(normal_range, tuple) or len(normal_range) != 2:
            print(f"Invalid range format for {param_name} (key={matched_key}): {normal_range}")
            return "unknown"
        
        min_val, max_val = normal_range
        
        if min_val <= numeric_value <= max_val:
            status = "normal"
        else:
            status = "abnormal"
        
        print(f"[CLASSIFY] {param_name}={numeric_value} | Predefined Range: [{min_val}, {max_val}] | Status: {status.upper()}")
        return status
            
    except Exception as e:
        print(f"Error classifying {param_name}={value}: {e}")
        return "unknown"

def segregate_parameters(lab_data_dict: dict) -> tuple[dict, dict, int, int]:
    """
    Segregate lab parameters into abnormal and normal categories.
    
    Returns:
        - abnormal_params: dict with abnormal parameter data
        - normal_params: dict with normal parameter data
        - abnormal_count: number of abnormal parameters
        - normal_count: number of normal parameters
    """
    abnormal_params = []
    normal_params = []
    unknown_params = []
    
    # Check primary parameter
    primary_name = lab_data_dict.get("parameterName", "")
    primary_value = lab_data_dict.get("currentValue", "")
    primary_normal_range = lab_data_dict.get("normalRange")
    
    if primary_name and primary_value:
        status = classify_parameter_status(primary_name, primary_value, primary_normal_range)
        primary_data = {
            "name": primary_name,
            "value": primary_value,
            "type": "primary",
            "status": status,
            "normalRange": primary_normal_range if primary_normal_range else None
        }
        
        if status == "abnormal":
            abnormal_params.append(primary_data)
            print(f"[ABNORMAL] Primary: {primary_name} = {primary_value}")
        elif status == "normal":
            normal_params.append(primary_data)
        else:
            # Unknown status - treat as normal but will be analyzed
            unknown_params.append(primary_data)
            print(f"[UNKNOWN] Primary: {primary_name} = {primary_value} - will analyze anyway")
    
    # Check linked parameters
    linked_data = lab_data_dict.get("linked_parameters", {}) or lab_data_dict.get("linkedParameters", {})
    
    print(f"\n[SEGREGATE] Processing {len(linked_data) if isinstance(linked_data, dict) else 0} linked parameters")
    
    if isinstance(linked_data, dict):
        for param_key, param_info in linked_data.items():
            if not isinstance(param_info, dict):
                print(f"[SEGREGATE] ⚠️ Skipping non-dict param: {param_key}")
                continue
            
            param_name = param_info.get("name", param_key)
            print(f"\n[SEGREGATE] Processing: {param_name} (key: {param_key})")
            print(f"[SEGREGATE]   Available keys: {list(param_info.keys())}")
            
            # Extract normalRange from input if available
            normal_range_str = param_info.get("normalRange")
            if normal_range_str:
                print(f"[SEGREGATE]   ✅ Input normalRange: '{normal_range_str}'")
            else:
                print(f"[SEGREGATE]   ⚠️  NO normalRange in input - will use predefined ranges")
            
            # Get current value - TRY MULTIPLE EXTRACTION PATHS
            current_value = None
            current_unit = ""
            
            # PATH 1: Try "current" object structure
            if "current" in param_info:
                current_data = param_info.get("current", {})
                print(f"[SEGREGATE]   Found 'current' key: {current_data}")
                if isinstance(current_data, dict):
                    current_value = current_data.get("value")
                    current_unit = current_data.get("unit", "")
                    print(f"[SEGREGATE]   ✓ Extracted from 'current': {current_value} {current_unit}")
            
            # PATH 2: Try "currentValues" array structure
            if not current_value and "currentValues" in param_info:
                current_vals = param_info.get("currentValues", [])
                print(f"[SEGREGATE]   Found 'currentValues' array: {current_vals}")
                if isinstance(current_vals, list) and current_vals:
                    # Take the FIRST entry (should be most recent)
                    first_val = current_vals[0]
                    if isinstance(first_val, dict):
                        current_value = first_val.get("value")
                        current_unit = first_val.get("unit", "")
                        print(f"[SEGREGATE]   ✓ Extracted from 'currentValues[0]': {current_value} {current_unit}")
                    else:
                        print(f"[SEGREGATE]   ⚠️ currentValues[0] is not a dict: {type(first_val)}")
            
            # PATH 3: Try direct "value" field (fallback)
            if not current_value and "value" in param_info:
                current_value = param_info.get("value")
                current_unit = param_info.get("unit", "")
                print(f"[SEGREGATE]   ✓ Extracted from direct 'value': {current_value} {current_unit}")
            
            if current_value:
                print(f"[SEGREGATE]   ✅ FINAL VALUE: {param_name} = {current_value} {current_unit}")
                
                status = classify_parameter_status(param_name, current_value, normal_range_str)
                linked_param_data = {
                    "name": param_name,
                    "value": f"{current_value} {current_unit}".strip(),
                    "type": "linked",
                    "status": status,
                    "key": param_key,
                    "normalRange": normal_range_str if normal_range_str else None
                }
                
                if status == "abnormal":
                    abnormal_params.append(linked_param_data)
                    print(f"[ABNORMAL] Linked: {param_name} = {current_value} {current_unit}")
                elif status == "normal":
                    normal_params.append(linked_param_data)
                    print(f"[NORMAL] Linked: {param_name} = {current_value} {current_unit}")
                else:
                    unknown_params.append(linked_param_data)
                    print(f"[UNKNOWN] Linked: {param_name} = {current_value} {current_unit} - will analyze anyway")
            else:
                print(f"[SEGREGATE]   ❌ FAILED TO EXTRACT CURRENT VALUE for {param_name}")
                print(f"[SEGREGATE]   Full param_info: {param_info}")
    
    # Combine unknown with normal, but they'll still be analyzed if values look concerning
    all_normal = normal_params + unknown_params
    
    print(f"\n=== PARAMETER CLASSIFICATION SUMMARY ===")
    print(f"Abnormal: {len(abnormal_params)}")
    for param in abnormal_params:
        print(f"  - {param['name']}: {param['value']}")
    print(f"Normal: {len(normal_params)}")
    for param in normal_params[:5]:  # First 5 only
        print(f"  - {param['name']}: {param['value']}")
    print(f"Unknown (need range): {len(unknown_params)}")
    print(f"========================================\n")
    
    return abnormal_params, all_normal, len(abnormal_params), len(all_normal)


def select_parameters_with_priority(abnormal_params: list, normal_params: list, lab_data_dict: dict, max_total: int = 100, is_followup: bool = False) -> tuple:
    """
    Select parameters using priority system:

    FOLLOW-UP REPORT (is_followup=True):
      Step 1: Include ALL abnormal parameters (no limit)
      Step 2: If abnormal count >= 10 → STOP, do NOT include any normal parameters
              If abnormal count < 10  → include normal parameters to fill up to min 10 total

    FIRST-TIME REPORT (is_followup=False):
      Step 1: Include ALL abnormal parameters
      Step 2: Include ALL normal parameters that have previousValues
      Step 3: Include ALL remaining normal parameters (ensure at least 15 total)

    Args:
        abnormal_params: List of abnormal parameter dicts with 'name', 'value', 'key' fields
        normal_params: List of normal parameter dicts with 'name', 'value', 'key' fields
        lab_data_dict: Full lab data dict to check for previousValues
        max_total: Soft ceiling (default 100 = effectively unlimited)
        is_followup: Whether this is a follow-up report (controls normal param inclusion)

    Returns:
        tuple: (selected_abnormal, selected_normal, total_count)
    """
    print(f"\n{'='*80}")
    print(f"[PARAMETER SELECTION] Starting 3-step priority selection")
    print(f"{'='*80}")
    print(f"Input: {len(abnormal_params)} abnormal, {len(normal_params)} normal parameters")
    
    # STEP 1: Include ALL abnormal parameters (no limit)
    selected_abnormal = abnormal_params.copy()
    print(f"\n[STEP 1] Selected ALL {len(selected_abnormal)} abnormal parameters:")
    for param in selected_abnormal:
        print(f"  ✓ {param['name']} = {param['value']}")
    
    # ── FOLLOW-UP REPORT LOGIC ──────────────────────────────────────────────────
    if is_followup:
        print(f"\n[STEP 2 - FOLLOW-UP] Abnormal count = {len(selected_abnormal)}")
        if len(selected_abnormal) >= 10:
            # ≥10 abnormal params → show ONLY abnormal, skip all normal
            print(f"[STEP 2 - FOLLOW-UP] ≥10 abnormal params → EXCLUDING all normal parameters")
            selected_normal = []
        else:
            # <10 abnormal → fill with normal params up to a minimum of 10 total
            min_target_followup = 10
            slots_needed = min_target_followup - len(selected_abnormal)
            print(f"[STEP 2 - FOLLOW-UP] <10 abnormal → adding up to {slots_needed} normal params to reach total of {min_target_followup}")

            # Prefer normal params that have previousValues first
            linked_params_data = lab_data_dict.get('linkedParameters', {}) or lab_data_dict.get('linked_parameters', {})
            primary_param_name = lab_data_dict.get('parameterName', '')
            primary_has_previous = bool(lab_data_dict.get('previousValues', []))

            comparative_params = []
            remaining_normal_params = []
            for param in normal_params:
                param_name = param['name']
                has_previous = False
                if param_name == primary_param_name:
                    has_previous = primary_has_previous
                else:
                    for lp_key, lp_data in linked_params_data.items():
                        if isinstance(lp_data, dict) and lp_data.get('name') == param_name:
                            prev_vals = lp_data.get('previousValues', [])
                            has_previous = bool(prev_vals and isinstance(prev_vals, list) and
                                              any(v.get('value') for v in prev_vals if isinstance(v, dict)))
                            break
                if has_previous:
                    comparative_params.append(param)
                else:
                    remaining_normal_params.append(param)

            # Fill slots: comparative first, then remaining, up to slots_needed
            combined_normal = comparative_params + remaining_normal_params
            selected_normal = combined_normal[:slots_needed] if slots_needed > 0 else []
            for param in selected_normal:
                print(f"  ✓ NORMAL (fill): {param['name']} = {param['value']}")

        final_total = len(selected_abnormal) + len(selected_normal)

    # ── FIRST-TIME REPORT LOGIC ──────────────────────────────────────────────────
    else:
        comparative_params = []
        remaining_normal_params = []

        # Get linked parameters data to check for previousValues
        linked_params_data = lab_data_dict.get('linkedParameters', {}) or lab_data_dict.get('linked_parameters', {})
        primary_param_name = lab_data_dict.get('parameterName', '')
        primary_has_previous = bool(lab_data_dict.get('previousValues', []))

        print(f"\n[STEP 2] Checking which parameters have previousValues for comparison:")

        # Categorize normal parameters based on previousValues presence
        for param in normal_params:
            param_name = param['name']
            has_previous = False

            if param_name == primary_param_name:
                has_previous = primary_has_previous
                print(f"  [CHECK] {param_name}: Primary parameter, has_previous={has_previous}")
            else:
                for lp_key, lp_data in linked_params_data.items():
                    if isinstance(lp_data, dict) and lp_data.get('name') == param_name:
                        prev_vals = lp_data.get('previousValues', [])
                        has_previous = bool(prev_vals and isinstance(prev_vals, list) and
                                          any(v.get('value') for v in prev_vals if isinstance(v, dict)))
                        print(f"  [CHECK] {param_name}: Found in linkedParameters, previousValues={len(prev_vals) if isinstance(prev_vals, list) else 0}, has_previous={has_previous}")
                        break

            if has_previous:
                comparative_params.append(param)
                print(f"  ✓ COMPARATIVE: {param_name} (has previous values for comparison)")
            else:
                remaining_normal_params.append(param)
                print(f"  • REMAINING: {param_name} (no previous values)")

        selected_comparative = comparative_params.copy()
        print(f"\n[STEP 2] Selected {len(selected_comparative)} comparative parameters for trend analysis")

        # STEP 3: Include ALL remaining normal parameters (no hard cap — ensure at least 15 total)
        current_total = len(selected_abnormal) + len(selected_comparative)
        print(f"\n[STEP 3] Current total: {current_total} (abnormal: {len(selected_abnormal)} + comparative: {len(selected_comparative)})")

        selected_remaining = remaining_normal_params.copy()  # Include ALL remaining normal params
        if selected_remaining:
            print(f"[STEP 3] Adding ALL {len(selected_remaining)} remaining normal parameters")
            for param in selected_remaining:
                print(f"  ✓ {param['name']} = {param['value']}")
        else:
            print(f"[STEP 3] No remaining normal parameters to add")

        # Combine all selected normal parameters
        selected_normal = selected_comparative + selected_remaining
        final_total = len(selected_abnormal) + len(selected_normal)
    
    print(f"\n{'='*80}")
    print(f"[PARAMETER SELECTION] FINAL SELECTION SUMMARY")
    print(f"{'='*80}")
    print(f"Abnormal (all): {len(selected_abnormal)}")
    print(f"Normal selected: {len(selected_normal)}")
    print(f"TOTAL SELECTED: {final_total}")
    print(f"{'='*80}\n")
    
    return selected_abnormal, selected_normal, final_total

def ensure_json_safe(obj):
    """Ensure all objects are JSON serializable."""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            import base64
            return base64.b64encode(obj).decode("utf-8")
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: ensure_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [ensure_json_safe(v) for v in obj]
    else:
        return obj

def format_lab_data_toon(lab_data_dict: dict, previous_summaries: list = None, is_followup: bool = False) -> str:
    """
    Format lab data in compact plain text format (TOON) - optimized for token reduction.
    PRIORITIZES abnormal parameters first, then normal parameters.
    Clearly distinguishes between current and previous values for both primary and linked parameters.
    HIGHLIGHTS abnormal/risky parameters with ⚠️ markers.
    SHOWS TEMPORAL COMPARISON with trends when previous data exists.
    
    Args:
        lab_data_dict: Lab data dictionary with current values
        previous_summaries: List of previous report summaries (for parameter selection logic)
    """
    
    print(f"\n{'='*80}")
    print(f"[FORMAT_LAB_DATA_TOON] Starting data formatting")
    print(f"{'='*80}")
    
    parameter = lab_data_dict.get("parameterName", "Unknown")
    current_value = lab_data_dict.get("currentValue", "N/A")
    report_date = lab_data_dict.get("ReportDate") or lab_data_dict.get("report_date", "N/A")
    
    print(f"[FORMAT] Primary: {parameter} = {current_value}")
    print(f"[FORMAT] Report Date: {report_date}")
    
    # DEBUG: Show linkedParameters structure
    linked_params = lab_data_dict.get("linkedParameters", {}) or lab_data_dict.get("linked_parameters", {})
    if linked_params:
        print(f"[FORMAT] LinkedParameters count: {len(linked_params)}")
        for idx, (key, val) in enumerate(list(linked_params.items())[:3], 1):
            print(f"[FORMAT]   Sample {idx} - {key}:")
            if isinstance(val, dict):
                print(f"[FORMAT]     Keys: {list(val.keys())}")
                if "currentValues" in val:
                    print(f"[FORMAT]     currentValues: {val.get('currentValues')}")
                if "current" in val:
                    print(f"[FORMAT]     current: {val.get('current')}")
                if "value" in val:
                    print(f"[FORMAT]     value: {val.get('value')}")
    else:
        print(f"[FORMAT] No linkedParameters found!")
    print(f"{'='*80}\n")
    
    # Segregate parameters into abnormal and normal
    abnormal_params_all, normal_params_all, abnormal_count_all, normal_count_all = segregate_parameters(lab_data_dict)
    
    # Apply parameter selection logic — follow-up: abnormal only (or fill to 10); first-time: all
    abnormal_params, normal_params, total_selected = select_parameters_with_priority(
        abnormal_params_all,
        normal_params_all,
        lab_data_dict,
        max_total=100,
        is_followup=is_followup
    )
    
    abnormal_count = len(abnormal_params)
    normal_count = len(normal_params)
    
    print(f"[SELECTION] After priority filtering: {abnormal_count} abnormal + {normal_count} normal = {total_selected} total")
    
    # ===== HELPER FUNCTION TO CALCULATE TRENDS =====
    def calculate_trend(param_name: str, current_val_str: str, prev_values: list, current_date: str) -> dict:
        """Calculate trend and percentage change between current and most recent previous value
        
        Returns a dict with: current_value, current_date, previous_value, previous_date, change_type, change_percent
        Note: Takes the LAST (most recent) entry from previousValues array
        """
        if not prev_values or not isinstance(prev_values, list):
            print(f"[TREND] {param_name}: No previousValues (empty or not a list)")
            return None
        
        # DEBUG: Print raw previousValues data
        print(f"[TREND] {param_name}: RAW previousValues = {prev_values}")
        
        # Get most recent previous value (LAST entry in array)
        valid_prev = [v for v in prev_values if isinstance(v, dict) and v.get('value')]
        if not valid_prev:
            print(f"[TREND] {param_name}: No valid previousValues entries")
            return None
        
        # IMPORTANT: Take the LAST entry (most recent)
        most_recent = valid_prev[-1]
        prev_val_str = most_recent.get('value', '')
        prev_date = most_recent.get('date', 'Unknown')
        prev_unit = most_recent.get('unit', '')
        
        print(f"[TREND] {param_name}: EXTRACTED from dict -> value='{prev_val_str}', date='{prev_date}', unit='{prev_unit}'")
        print(f"[TREND] {param_name}: Total previousValues available: {len(valid_prev)}")
        
        # Build result dict with unit
        prev_with_unit = f"{prev_val_str} {prev_unit}".strip() if prev_unit else prev_val_str
        
        result = {
            'current_value': current_val_str,
            'current_date': current_date,
            'previous_value': prev_with_unit,
            'previous_date': prev_date,
            'change_type': 'Unknown',
            'change_percent': '0.0'
        }
        
        try:
            # Try to extract numeric values
            import re
            current_num = float(re.search(r'[0-9.]+', str(current_val_str)).group())
            prev_num = float(re.search(r'[0-9.]+', str(prev_val_str)).group())
            
            change = current_num - prev_num
            percent_change = (change / prev_num) * 100 if prev_num != 0 else 0
            
            # Determine trend direction
            if abs(percent_change) < 2:  # Less than 2% change is stable
                result['change_type'] = "STABLE"
                result['change_percent'] = f"{abs(percent_change):.1f}"
            elif change > 0:
                result['change_type'] = "INCREASED"
                result['change_percent'] = f"{abs(percent_change):.1f}"
            else:
                result['change_type'] = "DECREASED"
                result['change_percent'] = f"{abs(percent_change):.1f}"
            
        except:
            # If numeric comparison fails, still return the data
            result['change_type'] = 'Changed'
            result['change_percent'] = 'N/A'
        
        return result
    
    # ===== BUILD ABNORMAL PARAMETERS SECTION (CURRENT VALUES ONLY - NO TRENDS) =====
    abnormal_section = []
    normal_section = []
    trend_details = []  # Collect trend info separately
    
    # ===== BUILD UNIFIED PARAMETER LIST (ALL PARAMETERS IN ONE SEQUENCE) =====
    # Instead of separate abnormal/normal sections, create ONE unified list
    unified_param_list = []
    
    print(f"\n[FORMAT] Building unified parameter list:")
    print(f"[FORMAT]   {len(abnormal_params)} abnormal + {len(normal_params)} normal = {len(abnormal_params) + len(normal_params)} total")
    
    # Combine all parameters in priority order: abnormal first, then normal
    all_params_ordered = []
    
    # Add abnormal parameters first
    for param in abnormal_params:
        all_params_ordered.append({
            'name': param['name'],
            'value': param['value'],
            'is_abnormal': True,
            'normalRange': param.get('normalRange')
        })
        print(f"[FORMAT]   Added abnormal: {param['name']} = {param['value']}")
    
    # Add normal parameters after
    for param in normal_params:
        all_params_ordered.append({
            'name': param['name'],
            'value': param['value'],
            'is_abnormal': False,
            'normalRange': param.get('normalRange')
        })
        print(f"[FORMAT]   Added normal: {param['name']} = {param['value']}")
    
    # ===== BUILD PREVIOUS-VALUE LOOKUP FROM PAYLOAD =====
    # Key: normalised param name → {'prev_value': str, 'prev_date': str}
    _prev_lookup: dict = {}

    # Primary parameter
    _primary_prev = lab_data_dict.get("previousValues", [])
    if isinstance(_primary_prev, list):
        _valid = [v for v in _primary_prev if isinstance(v, dict) and v.get("value")]
        if _valid:
            _latest = _valid[-1]
            _prev_lookup[parameter.strip().lower()] = {
                "prev_value": f"{_latest.get('value', '')} {_latest.get('unit', '')}".strip(),
                "prev_date": _latest.get("date", ""),
            }

    # Linked parameters
    _linked_for_prev = lab_data_dict.get("linkedParameters", {}) or lab_data_dict.get("linked_parameters", {})
    if isinstance(_linked_for_prev, dict):
        for _pk, _pi in _linked_for_prev.items():
            if not isinstance(_pi, dict):
                continue
            _pname = _pi.get("name", _pk)
            _pvs = _pi.get("previousValues", [])
            if not isinstance(_pvs, list):
                continue
            _valid_pvs = [v for v in _pvs if isinstance(v, dict) and v.get("value")]
            if _valid_pvs:
                _lat = _valid_pvs[-1]
                _prev_lookup[_pname.strip().lower()] = {
                    "prev_value": f"{_lat.get('value', '')} {_lat.get('unit', '')}".strip(),
                    "prev_date": _lat.get("date", ""),
                }

    # Now build the unified section with sequential numbering
    unified_param_list.append(f"⚠️ ALL PARAMETERS TO ANALYZE ({len(all_params_ordered)} total - EVERY ONE MUST BE DISCUSSED):")
    unified_param_list.append(f"")
    
    for idx, param_info in enumerate(all_params_ordered, 1):
        param_name = param_info['name']
        param_value = param_info['value']
        is_abnormal = param_info['is_abnormal']
        normal_range = param_info.get('normalRange')
        
        # Mark abnormal with ⚠️, normal with ✓
        marker = "⚠️" if is_abnormal else "✓"
        
        # Extract unit from param_value if present (e.g., "210 mg/dL" -> "mg/dL")
        import re
        unit_match = re.search(r'([a-zA-Z/%^³²°\s]+)$', param_value.strip())
        unit = unit_match.group(1).strip() if unit_match else ""
        
        # Format normal range with unit if available
        normal_range_display = ""
        if normal_range:
            # Replace " - " with " to " for better readability
            range_formatted = str(normal_range).replace(" - ", " to ")
            
            # Check if normalRange already contains unit (alphabetic characters)
            has_unit = any(char.isalpha() for char in range_formatted)
            
            if has_unit:
                # Already has unit, use as is (e.g., "0.55 to 4.78 µIU/mL")
                normal_range_display = f" | Normal: {range_formatted}"
                print(f"[FORMAT]     Normal range (with unit): {range_formatted}")
            else:
                # No unit in range, append from value (e.g., "0.55 - 4.78" + "µIU/mL" -> "0.55 to 4.78 µIU/mL")
                if unit:
                    normal_range_display = f" | Normal: {range_formatted} {unit}"
                    print(f"[FORMAT]     Normal range (added unit): {range_formatted} {unit}")
                else:
                    normal_range_display = f" | Normal: {range_formatted}"
                    print(f"[FORMAT]     Normal range (no unit): {range_formatted}")

        # Show previous value inline if available in payload
        prev_info = _prev_lookup.get(param_name.strip().lower())
        if prev_info:
            prev_display = f" | Previous ({prev_info['prev_date']}): {prev_info['prev_value']}"
            print(f"[FORMAT] {param_name}: prev={prev_info['prev_value']} on {prev_info['prev_date']}")
        else:
            prev_display = ""
            print(f"[FORMAT] {param_name}: no previous value in payload")
        
        unified_param_list.append(f"  {idx}. {param_name}: {param_value} {marker}{normal_range_display}{prev_display}")
    
    # ===== PRIMARY PARAMETER DETAILS =====
    # Format previous values for primary parameter (historical data)
    prev_values = lab_data_dict.get("previousValues", [])
    
    # Ensure prev_values is a list
    if not isinstance(prev_values, list):
        prev_values = []
    
    # Filter valid entries and check for non-empty values
    valid_prev = []
    for v in prev_values:
        if isinstance(v, dict) and v.get("value"):
            valid_prev.append(v)
    
    if valid_prev:
        # Limit to last 3 entries
        prev_text = ", ".join([
            f"{v.get('date', 'N/A')}: {v.get('value', '')} {v.get('unit', '')}"
            for v in valid_prev[-3:]
        ])
        primary_history = f"Previous: {prev_text}"
    else:
        primary_history = "Previous: None (first report)"
    
    # ===== LINKED PARAMETERS CURRENT + PREVIOUS VALUES =====
    linked = lab_data_dict.get("linked_parameters", {}) or lab_data_dict.get("linkedParameters", {})
    linked_params_detailed = []
    
    # Ensure linked is a dict
    if not isinstance(linked, dict):
        linked = {}
    
    if linked:
        for param_key, param_info in linked.items():
            if not param_info or not isinstance(param_info, dict):
                continue
            
            param_name = param_info.get("name", param_key)
            
            # GET CURRENT VALUE - ROBUST EXTRACTION
            current_linked_value = "N/A"
            current_linked_unit = ""
            
            # PATH 1: Try "current" object structure
            if "current" in param_info:
                current_data = param_info.get("current", {})
                if isinstance(current_data, dict) and current_data.get("value"):
                    current_linked_value = current_data.get("value", "N/A")
                    current_linked_unit = current_data.get("unit", "")
                    print(f"[FORMAT-LINKED] {param_name}: Got current from 'current' → {current_linked_value} {current_linked_unit}")
            
            # PATH 2: Try "currentValues" array structure
            if current_linked_value == "N/A" and "currentValues" in param_info:
                current_vals = param_info.get("currentValues", [])
                if isinstance(current_vals, list) and current_vals:
                    for cv in current_vals:
                        if isinstance(cv, dict) and cv.get("value"):
                            current_linked_value = cv.get("value", "N/A")
                            current_linked_unit = cv.get("unit", "")
                            print(f"[FORMAT-LINKED] {param_name}: Got current from 'currentValues[0]' → {current_linked_value} {current_linked_unit}")
                            break
            
            # PATH 3: Try direct "value" field
            if current_linked_value == "N/A" and "value" in param_info:
                current_linked_value = param_info.get("value", "N/A")
                current_linked_unit = param_info.get("unit", "")
                print(f"[FORMAT-LINKED] {param_name}: Got current from direct 'value' → {current_linked_value} {current_linked_unit}")
            
            if current_linked_value == "N/A":
                print(f"[FORMAT-LINKED] ⚠️ {param_name}: FAILED to extract current value! Keys: {list(param_info.keys())}")
            
            # GET PREVIOUS VALUES
            prev_vals_text = []
            
            # Handle previous values in current/previous structure
            if "previous" in param_info:
                prev_vals = param_info.get("previous", [])
                if isinstance(prev_vals, list) and prev_vals:
                    for pv in prev_vals[-2:]:  # Last 2 previous values
                        if isinstance(pv, dict) and pv.get("value"):
                            prev_vals_text.append(f"{pv.get('value')} on {pv.get('date', 'N/A')}")
            
            # Handle previousValues structure (fallback)
            elif "previousValues" in param_info:
                prev_vals = param_info.get("previousValues", [])
                if isinstance(prev_vals, list) and prev_vals:
                    for pv in prev_vals[-2:]:  # Last 2 previous values
                        if isinstance(pv, dict) and pv.get("value"):
                            prev_vals_text.append(f"{pv.get('value')} on {pv.get('date', 'N/A')}")
            
            # Format: "Parameter: Current 210 mg/dL | Previous: 188 on 2026-02-08"
            param_line = f"{param_name}: Current {current_linked_value} {current_linked_unit}"
            if prev_vals_text:
                param_line += f" | Previous: {', '.join(prev_vals_text)}"
            else:
                param_line += " | Previous: None (first measurement)"
            
            linked_params_detailed.append(param_line)
    
    # Format linked parameters section with CURRENT + PREVIOUS
    linked_parameters_section = "\n  ".join(linked_params_detailed) if linked_params_detailed else "None"
    
    # ===== PATIENT INFO =====
    # Handle both direct fields and demographics object
    demographics = lab_data_dict.get("demographics", {})
    age = demographics.get("age") or lab_data_dict.get('age', 'N/A')
    gender = demographics.get("gender") or lab_data_dict.get('gender', 'N/A')
    bmi = demographics.get("bmi") or lab_data_dict.get('bmi', 'N/A')
    
    conditions = ", ".join(
        demographics.get("chronic_conditions", []) or
        lab_data_dict.get("chronicCondition", []) or 
        lab_data_dict.get("conditions", [])
    ) or "None"
    
    # ===== COMPACT SINGLE-REPORT FORMAT WITH UNIFIED PARAMETER LIST =====
    output = f"""📅 REPORT DATE: {report_date}

👤 PATIENT: Age {age}, {gender}, BMI {bmi}
🏥 CONDITIONS: {conditions}

{''.join(unified_param_list)}

⚠️ LEGEND:
- ⚠️ = ABNORMAL (requires detailed 8-12 line analysis + 🔄 TREND block if previous value exists)
- ✓ = NORMAL (requires 4-6 line explanation + 🔄 TREND block if previous value exists)
- "Previous (date): value" = previous result from payload — ALWAYS USE FOR COMPARISON

🚨 TREND RULE: If a parameter shows "| Previous (date): value" in the list above, you MUST include a 🔄 TREND ANALYSIS sub-section for it — NO EXCEPTIONS — whether it is ⚠️ ABNORMAL or ✓ NORMAL.

🚨 CRITICAL: You MUST discuss ALL {len(all_params_ordered)} parameters listed above!
🚨 Your "Understanding Your Results" section MUST have entries numbered 1 through {len(all_params_ordered)}!
🚨 DO NOT stop at parameter {abnormal_count} - continue through parameter {len(all_params_ordered)}!
"""

    # Add comparison/trend section when previous values exist in payload
    has_any_prev = bool(_prev_lookup)
    if has_any_prev:
        output += f"\n📈 TREND ANALYSIS — MANDATORY FOR FOLLOW-UP REPORT:\n"
        output += f"The following parameters have PREVIOUS values in the payload.\n"
        output += f"You MUST compare current vs previous for every parameter that has a 'Previous' value above.\n\n"
        output += f"COMPARISON TABLE:\n"

        # Build status-change intelligence: detect abnormal→normal and normal→abnormal crossings
        _status_changes = []   # list of dicts {name, prev_status, curr_status, label}
        _significant_changes = []  # params with > 10% numeric change

        for _pn, _pdata in _prev_lookup.items():
            # Find matching current param
            _curr_match = next(
                (p for p in all_params_ordered if p['name'].strip().lower() == _pn),
                None
            )
            if not _curr_match:
                continue
            _curr_str = _curr_match['value']
            _curr_is_abnormal = _curr_match['is_abnormal']
            output += f"  • {_curr_match['name']}: {_pdata['prev_value']} (on {_pdata['prev_date']}) → {_curr_str} (on {report_date})\n"

            # Detect status change: we can infer prev status by checking if prev value was in normal range
            # Use numeric % change as a proxy for significant fluctuation
            import re as _re
            try:
                _prev_num = float(_re.search(r'[\d.]+', str(_pdata['prev_value'])).group())
                _curr_num = float(_re.search(r'[\d.]+', str(_curr_str)).group())
                _pct = abs((_curr_num - _prev_num) / _prev_num * 100) if _prev_num else 0
                _direction = "↑ INCREASED" if _curr_num > _prev_num else ("↓ DECREASED" if _curr_num < _prev_num else "→ STABLE")
                _pct_str = f"{_pct:.1f}%"

                # Flag significant changes (>10% swing)
                if _pct >= 10:
                    _significant_changes.append({
                        'name': _curr_match['name'],
                        'direction': _direction,
                        'pct': _pct_str,
                        'prev': _pdata['prev_value'],
                        'curr': _curr_str,
                        'is_abnormal': _curr_is_abnormal,
                    })
            except Exception:
                _pct = 0
                _direction = "→"
                _pct_str = "N/A"

        # Add intelligent status-change and fluctuation summary
        if _significant_changes:
            output += f"\n🔁 SIGNIFICANT CHANGES DETECTED (≥10% fluctuation) — DISCUSS THESE IN DETAIL:\n"
            for _sc in _significant_changes:
                _flag = "⚠️ ABNORMAL" if _sc['is_abnormal'] else "✓ STILL NORMAL"
                output += f"  • {_sc['name']}: {_sc['direction']} {_sc['pct']} ({_sc['prev']} → {_sc['curr']}) [{_flag}]\n"

        output += (
            "\n🚨 MANDATORY FOR EVERY PARAMETER IN THE TABLE ABOVE (BOTH ⚠️ ABNORMAL AND ✓ NORMAL):\n"
            "Add a '🔄 TREND ANALYSIS' sub-section inside the entry for that parameter containing:\n"
            "  * Previous value: [value] on [date]\n"
            "  * Current value: [value] on [date]\n"
            "  * Change: [exact numeric difference] ([% change])\n"
            "  * Direction: IMPROVED / WORSENED / STABLE\n"
            "  * Clinical significance: 1-2 sentences explaining what this change means\n"
            "\nDO NOT skip the 🔄 TREND ANALYSIS block for ANY parameter that appears in the table above.\n"
            "Normal (✓) parameters with previous values ALSO require the full 🔄 TREND block.\n"
        )
    else:
        output += f"\nℹ️ No previous values provided in payload — analyzing current values as baseline.\n"

    output += f"""

⚠️ CRITICAL INSTRUCTIONS FOR ANALYSIS:
1. The CURRENT VALUES in the parameter list above are from {report_date}
2. You MUST analyze ALL {len(all_params_ordered)} parameters
3. Parameters marked ⚠️ need detailed analysis (8-12 lines each)
4. Parameters marked ✓ need 4-6 line explanation (NOT shorter — their 🔄 TREND block must still be included)
5. DO NOT skip ANY parameter — discuss ALL {len(all_params_ordered)} of them
6. {"✅ 🔄 TREND ANALYSIS IS MANDATORY FOR ALL {len(_prev_lookup)} PARAMETERS THAT HAVE PREVIOUS VALUES — this includes EVERY ✓ NORMAL parameter with a Previous entry" if has_any_prev else "No previous values in payload — treat all as baseline"}
7. {"DO NOT write a normal parameter entry without a 🔄 TREND block if it has a previous value. Skipping the trend for normal params is WRONG." if has_any_prev else ""}

⚠️ MANDATORY: Count your output entries! You MUST write entries 1, 2, 3, ... up to {len(all_params_ordered)}!

📊 REFERENCE: CURRENT VALUES FOR THIS REPORT ({report_date}):
"""
    
    # Build a clear reference of ALL current values
    current_values_list = []
    
    # Add ALL parameters in the same order as the unified list
    for idx, param_info in enumerate(all_params_ordered, 1):
        marker = "⚠️" if param_info['is_abnormal'] else "✓"
        current_values_list.append(f"  {idx}. {param_info['name']}: {param_info['value']} {marker}")
    
    output += "\n".join(current_values_list)
    output += f"""

⚠️ WHEN WRITING YOUR REPORT, USE ONLY THE CURRENT VALUES LISTED ABOVE FROM {report_date}!
{"⚠️ ALWAYS reference Previous values from the TREND ANALYSIS table when discussing each parameter!" if has_any_prev else ""}

🚨🚨🚨 FINAL COUNT VERIFICATION BEFORE YOU START WRITING 🚨🚨🚨

BEFORE you write a SINGLE WORD, answer these questions:
1. How many parameters are listed above? Answer: {len(all_params_ordered)}
2. How many entries must your "Understanding Your Results" section have? Answer: {len(all_params_ordered)}
3. What are the entry numbers you must write? Answer: 1, 2, 3, ..., {len(all_params_ordered)}

YOU MUST WRITE EXACTLY {len(all_params_ordered)} NUMBERED ENTRIES!

Parameter list breakdown:
- Entries 1-{abnormal_count}: ABNORMAL parameters (marked ⚠️) — 8-12 lines + 🔄 TREND block (if has previous value)
- Entries {abnormal_count + 1}-{len(all_params_ordered)}: NORMAL parameters (marked ✓) — 4-6 lines + 🔄 TREND block (REQUIRED if has previous value)

🚨 REMINDER: ALL {len(_prev_lookup)} parameters have previous values. Every single one needs a 🔄 TREND ANALYSIS sub-section.

⚠️ VERIFICATION REQUIREMENT:
- Your final output MUST have exactly {len(all_params_ordered)} numbered entries
- DO NOT skip normal parameters after discussing abnormal ones
- Count your entries BEFORE submitting: [1] [2] [3] ... [{len(all_params_ordered)}]
"""

    print(f"\n{'='*80}")
    print(f"[FORMAT_LAB_DATA_TOON] FINAL OUTPUT PREVIEW")
    print(f"{'='*80}")
    print(f"Total selected: {len(all_params_ordered)} parameters")
    print(f"Total output length: {len(output)} characters")
    
    # Show the unified parameter list
    print(f"\n[FORMAT] Unified parameter list (what LLM will see):")
    for idx, param_info in enumerate(all_params_ordered, 1):
        marker = "⚠️" if param_info['is_abnormal'] else "✓"
        print(f"  {idx}. {param_info['name']}: {param_info['value']} {marker}")
    
    print(f"\n[FORMAT] Trend details count: {len(trend_details)}")
    print(f"{'='*80}\n")

    return output


def has_valid_previous_data(lab_data_dict: dict) -> bool:
    """
    Check if there is any valid previous/historical data for comparison.
    Returns True only if there are non-empty previous values with dates before report date.
    """
    try:
        # Check primary parameter previous values
        prev_values = lab_data_dict.get("previousValues", [])
        
        # Ensure it's a list
        if not isinstance(prev_values, list):
            prev_values = []
        
        # Check for valid entries
        for v in prev_values:
            if isinstance(v, dict) and v.get("value") and v.get("date"):
                return True
        
        # Check linked parameters previous values
        linked = lab_data_dict.get("linkedParameters", {})
        
        # Ensure it's a dict
        if not isinstance(linked, dict):
            return False
        
        for param_info in linked.values():
            if not param_info or not isinstance(param_info, dict):
                continue
            
            prev_vals = param_info.get("previousValues", [])
            
            # Ensure it's a list
            if not isinstance(prev_vals, list):
                continue
            
            # Check for valid entries
            for v in prev_vals:
                if isinstance(v, dict) and v.get("value") and v.get("date"):
                    return True
        
        return False
    except Exception as e:
        print(f"Error checking previous data: {e}")
        return False

def estimate_tokens(text: str, model: str = "cl100k_base") -> int:
    """Estimate token count using tiktoken cl100k_base encoding (approximation for Groq/Llama models)."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return int(len(text) / 4)



"""Enhanced summary storage with structured parameter tracking"""

# Add this new function after the existing imports and before run_researcher_from_data

async def create_structured_summary(lab_data_dict: dict, main_insight: str, report_date: str) -> dict:
    """
    Create a structured summary that captures actual parameter values and interconnected health risks.
    
    This enables the model to:
    1. Know exact previous values for comparison
    2. Track trends over time
    3. Provide specific, data-driven insights
    4. Identify interconnected health conditions and their combined risks
    5. Generate comprehensive summaries that include multiple risk factors
    
    Returns:
        dict: Structured summary with parameters, values, interconnected risk analysis, and comprehensive summary text
    """
    # Extract primary parameter
    primary_param = {
        "name": lab_data_dict.get("parameterName", "Unknown"),
        "current_value": lab_data_dict.get("currentValue", "N/A"),
        "report_date": report_date,
        "unit": ""  # Extract from previousValues if available
    }
    
    # Extract unit from previousValues if available
    prev_values = lab_data_dict.get("previousValues", [])
    if prev_values and isinstance(prev_values, list):
        for pv in prev_values:
            if isinstance(pv, dict) and pv.get("unit"):
                primary_param["unit"] = pv.get("unit", "")
                break
    
    # Extract linked parameters with their current values (handle both naming conventions)
    linked_params = []
    linked_data = lab_data_dict.get("linked_parameters", {}) or lab_data_dict.get("linkedParameters", {})
    
    print(f"\\n[CREATE_STRUCTURED_SUMMARY] Extracting linked parameters")
    print(f"[CREATE_STRUCTURED_SUMMARY] Found {len(linked_data) if isinstance(linked_data, dict) else 0} linked params")
    
    if isinstance(linked_data, dict):
        for param_key, param_info in linked_data.items():
            if not isinstance(param_info, dict):
                print(f"[CREATE_STRUCTURED_SUMMARY] ⚠️ Skipping non-dict param: {param_key}")
                continue
                
            param_name = param_info.get("name", param_key)
            
            # ROBUST CURRENT VALUE EXTRACTION - TRY MULTIPLE PATHS
            current_value = "N/A"
            unit = ""
            
            # PATH 1: Try \"current\" object structure
            if "current" in param_info:
                current_data = param_info.get("current", {})
                if isinstance(current_data, dict) and current_data.get("value"):
                    current_value = current_data.get("value", "N/A")
                    unit = current_data.get("unit", "")
                    print(f"[CREATE_STRUCTURED_SUMMARY] ✓ {param_name}: Got from 'current' → {current_value} {unit}")
            
            # PATH 2: Try \"currentValues\" array structure
            if current_value == "N/A" and "currentValues" in param_info:
                current_vals = param_info.get("currentValues", [])
                if isinstance(current_vals, list) and current_vals:
                    for cv in current_vals:
                        if isinstance(cv, dict) and cv.get("value"):
                            current_value = cv.get("value", "N/A")
                            unit = cv.get("unit", "")
                            print(f"[CREATE_STRUCTURED_SUMMARY] ✓ {param_name}: Got from 'currentValues[0]' → {current_value} {unit}")
                            break
            
            # PATH 3: Try direct \"value\" field (fallback)
            if current_value == "N/A" and "value" in param_info:
                current_value = param_info.get("value", "N/A")
                unit = param_info.get("unit", "")
                print(f"[CREATE_STRUCTURED_SUMMARY] ✓ {param_name}: Got from direct 'value' → {current_value} {unit}")
            
            if current_value == "N/A":
                print(f"[CREATE_STRUCTURED_SUMMARY] ❌ {param_name}: FAILED extraction! Keys: {list(param_info.keys())}")
            
            linked_params.append({
                "name": param_name,
                "value": str(current_value),
                "unit": unit
            })
    
    # Extract patient context from demographics or direct fields
    demographics = lab_data_dict.get("demographics", {})
    patient_context = {
        "age": demographics.get("age") or lab_data_dict.get("age"),
        "gender": demographics.get("gender") or lab_data_dict.get("gender"),
        "bmi": demographics.get("bmi") or lab_data_dict.get("bmi"),
        "conditions": (
            demographics.get("chronic_conditions") or 
            lab_data_dict.get("chronicCondition", []) or 
            lab_data_dict.get("conditions", [])
        )
    }
    
    # Generate an enhanced summary that includes interconnected health factors
    summary_text = f"Report Date: {report_date}. "
    summary_text += f"{primary_param['name']} is {primary_param['current_value']}{primary_param['unit']}"
    
    # Add linked parameters with context
    if linked_params:
        param_details = []
        for lp in linked_params[:4]:  # Include up to 4 linked parameters
            param_details.append(f"{lp['name'].lower().replace('blood ', '').replace(' blood', '')} ({lp['value']} {lp['unit']})")
        
        if param_details:
            summary_text += f" with {', '.join(param_details[:-1])}"
            if len(param_details) > 1:
                summary_text += f", and {param_details[-1]}"
            else:
                summary_text += f" {param_details[0]}"
    
    # Add BMI if available
    if patient_context.get("bmi"):
        summary_text += f", and BMI {patient_context['bmi']}"
    
    # Extract and summarize the "How Your Health Factors Connect" section from the main analysis
    interconnection_summary = ""
    if main_insight:
        try:
            # Use Groq to extract the interconnection analysis
            from langchain_core.prompts import ChatPromptTemplate
            
            extraction_model = get_configured_chat_model(
                temperature=0,
                max_tokens=200
            )
            
            extraction_prompt = ChatPromptTemplate.from_template("""
            Extract and summarize the "🔗 How Your Health Factors Connect" section from the following medical analysis.
            
            Focus on:
            1. How the different health parameters reinforce each other
            2. The combined risks they create
            3. Why integrated management is important
            
            Provide a concise 1-2 sentence summary that captures the key interconnections and risks.
            If no such section exists, return "No interconnection analysis found."
            
            Medical Analysis:
            {analysis}
            
            Interconnection Summary:
            """)
            
            chain = extraction_prompt | extraction_model
            response = await chain.ainvoke({"analysis": main_insight})
            
            extracted_text = response.content.strip()
            if extracted_text and extracted_text != "No interconnection analysis found.":
                interconnection_summary = f" {extracted_text}"
                
        except Exception as e:
            # Fallback: Try to find and extract the section manually
            lines = main_insight.split('\n')
            in_connection_section = False
            connection_content = []
            
            for line in lines:
                if "🔗 How Your Health Factors Connect" in line or "How Your Health Factors Connect" in line:
                    in_connection_section = True
                    continue
                elif in_connection_section and line.strip().startswith('###') and 'connect' not in line.lower():
                    break
                elif in_connection_section and line.strip():
                    connection_content.append(line.strip())
            
            if connection_content:
                # Take key sentences that mention risks and connections
                key_sentences = []
                for content in connection_content[:3]:  # First 3 lines
                    if any(word in content.lower() for word in ['increase', 'risk', 'together', 'combination', 'interconnected']):
                        key_sentences.append(content)
                        break
                
                if key_sentences:
                    interconnection_summary = f" {key_sentences[0][:150]}..."
    
    # Add the interconnection summary to the main summary text
    if interconnection_summary:
        summary_text += f".{interconnection_summary}"
    
    return {
        "report_date": report_date,
        "summary_text": summary_text.strip(),
        "primary_parameter": primary_param,
        "linked_parameters": linked_params,
        "patient_context": patient_context,
        "is_followup": has_valid_previous_data(lab_data_dict)
    }


def format_previous_summaries_for_context(previous_summaries: list, current_report_date: str) -> str:
    """
    Format previous summary texts into contextual background for the model.

    Qdrant now stores only summary_text (no parameter-level data).  This
    context is used exclusively so the model understands what was previously
    discussed (past recommendations, health focus areas, improvements noted,
    etc.).  It must NOT be used for trend analysis or value comparisons —
    those must come from the previousValues in the request payload.

    Args:
        previous_summaries: List of previous summary dicts from Qdrant.
                            Each dict has 'summary' -> {'summary_text': ..., 'report_date': ...}
        current_report_date: Date of current report being analyzed

    Returns:
        str: Contextual background text for the model
    """
    if not previous_summaries:
        return "No previous reports available. This is the patient's first analysis."

    # Sort by date (most recent first) and cap at 3 for token efficiency
    sorted_summaries = sorted(
        previous_summaries,
        key=lambda x: x.get('date', ''),
        reverse=True
    )[:3]

    context_parts = [
        "📜 PAST REPORT CONTEXT (for model awareness only — do NOT use for trend analysis):\n",
        f"⚠️  Current report date: {current_report_date}",
        "⚠️  The summaries below describe what was covered in PREVIOUS sessions.",
        "⚠️  Use this context to understand the patient's history, prior recommendations,",
        "    and ongoing health themes. For actual value comparisons and trend analysis,",
        "    use ONLY the previousValues provided in the current request payload.\n",
    ]

    for idx, summary_entry in enumerate(reversed(sorted_summaries), 1):
        summary_data = summary_entry.get('summary', {})
        date = summary_entry.get('date', 'Unknown date')

        # Extract text regardless of old/new format
        if isinstance(summary_data, str):
            summary_text = summary_data
        elif isinstance(summary_data, dict):
            summary_text = (
                summary_data.get('summary_text', '')
                or summary_data.get('narrative_summary', '')
            )
            date = summary_data.get('report_date', date)
        else:
            summary_text = ""

        if summary_text:
            context_parts.append(
                f"\n🔙 Past Report {idx} [{date}]:\n   {summary_text[:300]}"
            )

    context_parts.append(
        "\n\n⚠️  REMINDER: All numerical trend comparisons MUST rely on the "
        "previousValues fields in the current request. Do not infer values from "
        "the text above."
    )

    return "\n".join(context_parts)


# UPDATED run_researcher_from_data function
async def run_researcher_from_data(lab_data_dict: dict, user_id: str = None, model: str = "openai"):
    """
    ENHANCED VERSION: Generates clinical insights with structured summary storage
    for meaningful historical comparison.
    Supports both OpenAI and Perplexity models.
    
    Args:
        lab_data_dict: Lab data dictionary with parameters and values
        user_id: User identifier
        model: "openai" or "perplexity" - determines which API to use
    """
    if not user_id:
        user_id = str(uuid.uuid4())
    
    # Extract report date
    report_date = lab_data_dict.get("ReportDate") or lab_data_dict.get("report_date")
    if not report_date:
        report_date = datetime.now().strftime("%Y-%m-%d")
        print(f"Warning: No ReportDate found, using today: {report_date}")
    
    lab_data_dict['report_date'] = report_date

    # Get previous summaries with structured data
    previous_summaries = get_user_summaries(user_id)

    # Create enhanced memory context with actual parameter values
    if previous_summaries:
        memory_context = format_previous_summaries_for_context(previous_summaries, report_date)
    else:
        memory_context = "New patient - no previous reports"

    # Check if this is a follow-up report
    # Check if this is a follow-up report (user has previous data in database)
    is_followup_report = bool(previous_summaries) and len(previous_summaries) > 0  
    
    # Use TOON-formatted data with parameter selection logic
    formatted_data = format_lab_data_toon(lab_data_dict, previous_summaries, is_followup=is_followup_report)

    # Enhanced query with structured historical context
    if is_followup_report:
        report_type_instruction = """This is a FOLLOW-UP REPORT with historical comparison data.
- Compare current values (from report date) with previous values (from earlier dates shown in history)
- Note specific improvements, declines, or stability for EACH parameter
- Acknowledge patient effort if values improved
- Provide specific numerical comparisons (e.g., "HbA1c improved from 8.2% to 7.1%")"""
    else:
        report_type_instruction = """This is a FIRST-TIME REPORT with no historical data.
- Analyze current values as baseline measurements
- DO NOT create false comparisons or assume previous data exists
- Focus on establishing health status and setting goals
- Explain what normal ranges are and where patient stands"""

    query = f"""{memory_context}

{report_type_instruction}

Today's Date: {datetime.now().strftime("%Y-%m-%d")}

{formatted_data}

Provide comprehensive clinical analysis (under 600 words):

⚠️ CRITICAL INSTRUCTION - COMPLETE PARAMETER COVERAGE MANDATORY:
   
   YOU MUST ANALYZE EVERY SINGLE ABNORMAL PARAMETER - NO EXCEPTIONS!
   
   ABNORMAL PARAMETERS (marked with ⚠️):
   - Provide DETAILED explanation (3-5 lines each)
   - Explain health risks and complications
   - Include specific numerical context (current value vs normal range)
   - Discuss clinical significance
   - DO NOT skip any abnormal parameter even if there are many
   
   NORMAL PARAMETERS:
   - Simply state "Normal" or "Within normal range"
   - No detailed explanation needed (1 line maximum)

1. ABNORMAL PARAMETERS ANALYSIS (PRIMARY FOCUS - ANALYZE EVERY SINGLE ONE):
   ⚠️ MANDATORY: You MUST analyze EVERY abnormal parameter marked with ⚠️ in the data above
   ⚠️ COUNT all abnormal parameters first and ensure you cover each one
   ⚠️ If there are 6 abnormal parameters, you MUST discuss all 6 - not 3 or 4
   
   For EACH AND EVERY abnormal parameter:
     * State the parameter name, current value, and normal range
     * Explain WHY it's concerning (specific health risks in detail)
     * Mention severity level (mildly/moderately/severely abnormal)
     * If follow-up: Show trend with previous values and direction
   
   After individual analysis:
     * Explain interconnected risks between multiple abnormal parameters
     * Discuss how they compound each other's effects

2. NORMAL PARAMETERS (BRIEF ACKNOWLEDGMENT):
   - List all normal parameters in one line
   - Simply state "within normal range"
   - No further explanation unless specifically relevant

3. RISK ASSESSMENT (Focus on Abnormal Only):
   - Immediate health risks from ALL abnormal values
   - Long-term complications if not addressed
   - Combined risk when multiple parameters abnormal
   - Prioritize most critical risks

4. RECOMMENDATIONS (Prioritized by Abnormality):
   - Specific actions for EACH abnormal parameter (mention each by name)
   - Dietary changes (Indian context, practical advice)
   - Lifestyle modifications for each concern
   - Monitoring frequency
   - When to see doctor urgently

⚠️ QUALITY CHECK BEFORE RESPONDING:
- Count abnormal parameters in the data (marked with ⚠️)
- Verify you discussed EACH one individually
- If data shows 6 abnormal parameters but you only discussed 4, you FAILED

STRUCTURE: Start with abnormal parameters section (covering ALL of them), then briefly list normal ones, then recommendations.
Use dashes (-) for bullet points only. Be thorough for ALL abnormal parameters, brief for normal."""

    # Always use OpenAI (GPT-4o-mini)
    response = await deep_researcher.ainvoke({
        "messages": [("user", query)],
        "user_id": user_id,
        "report_date": report_date,
        "is_followup": is_followup_report
    })
    main_insight = response.get("final_report") if isinstance(response, dict) else str(response)
    usage_main = response.get("usage") if isinstance(response, dict) else None

    if usage_main:
        usage_main = {
            "prompt_tokens": usage_main.get("prompt_tokens", 0),
            "completion_tokens": usage_main.get("completion_tokens", 0),
            "total_tokens": usage_main.get("total_tokens", 0),
        }
    else:
        est_tokens = estimate_tokens(query + main_insight)
        usage_main = {
            "prompt_tokens": int(est_tokens * 0.6),
            "completion_tokens": int(est_tokens * 0.4),
            "total_tokens": est_tokens,
        }

    # Create structured summary with actual parameter values
    structured_summary = await create_structured_summary(lab_data_dict, main_insight, report_date)

    # Generate a brief narrative summary for display (2-3 sentences)
    summarizer = get_configured_chat_model()

    if is_followup_report and previous_summaries:
        # For follow-up, create a summary that highlights changes.
        # NOTE: Qdrant stores only summary_text now — no primary_parameter data.
        last_summary = previous_summaries[0]  # newest first
        last_summary_data = last_summary.get('summary', {})
        prev_context = (
            last_summary_data.get('summary_text', '')
            or (str(last_summary_data) if not isinstance(last_summary_data, dict) else '')
        )[:150]
        
        current_value = f"{structured_summary['primary_parameter']['current_value']} {structured_summary['primary_parameter']['unit']}"
        
        summary_prompt = ChatPromptTemplate.from_template(
            """Summarize the follow-up report in 2-3 sentences focusing on parameter changes.
            
Previous report context: {previous}
Current {param_name}: {current_value}
Current insights: {insight}

Highlight: 1) Parameter change with specific values (use previousValues from insights), 2) Clinical significance, 3) Brief recommendation."""
        )
        summary_input = {
            "insight": main_insight[:500],
            "previous": prev_context,
            "param_name": structured_summary['primary_parameter']['name'],
            "current_value": current_value
        }
    else:
        # First-time report summary
        summary_prompt = ChatPromptTemplate.from_template(
            """Summarize first-time report in 2-3 sentences with key parameter values.

Report date: {report_date}
{param_name}: {current_value}
Insights: {insight}

Include: 1) Primary parameter value and interpretation, 2) Key health concern, 3) Main recommendation."""
        )
        summary_input = {
            "insight": main_insight[:500],
            "report_date": report_date,
            "param_name": structured_summary['primary_parameter']['name'],
            "current_value": f"{structured_summary['primary_parameter']['current_value']} {structured_summary['primary_parameter']['unit']}"
        }

    summary_response = await (summary_prompt | summarizer).ainvoke(summary_input)
    narrative_summary = summary_response.content.strip()

    # Update structured summary with narrative
    structured_summary['narrative_summary'] = narrative_summary

    usage_summary = getattr(summary_response, "usage", None)
    if usage_summary:
        usage_summary = {
            "prompt_tokens": usage_summary.prompt_tokens,
            "completion_tokens": usage_summary.completion_tokens,
            "total_tokens": usage_summary.total_tokens,
        }
    else:
        est_tokens = estimate_tokens(narrative_summary)
        usage_summary = {
            "prompt_tokens": int(est_tokens * 0.5),
            "completion_tokens": int(est_tokens * 0.5),
            "total_tokens": est_tokens,
        }

    total_usage = {
        "prompt_tokens": int(usage_main["prompt_tokens"]) + int(usage_summary["prompt_tokens"]),
        "completion_tokens": int(usage_main["completion_tokens"]) + int(usage_summary["completion_tokens"]),
        "total_tokens": int(usage_main["total_tokens"]) + int(usage_summary["total_tokens"]),
    }

    # Save ONLY the narrative summary_text to Qdrant for contextual memory.
    # Full parameter-level data is NOT stored in Qdrant.
    save_summary(user_id, narrative_summary, date=report_date)

    return ensure_json_safe({
        "status": "success",
        "user_id": user_id,
        "report_date": report_date,
        "model_used": model,
        "final_result": main_insight,
        "summary": narrative_summary,  # Brief narrative for API response
        "structured_summary": structured_summary,  # Full structured data for reference
        "is_continuation": bool(previous_summaries),
        "is_followup_report": is_followup_report,
        "usage": total_usage,
    })

async def run_researcher_from_s3(s3info: dict, user_id: str = None, model: str = "openai", use_tavily: bool = True):
    """
    TOON-optimized version: Process S3 files with reduced token usage.
    Supports both OpenAI and Perplexity models.
    
    Args:
        s3info: S3 file information dictionary
        user_id: User identifier
        model: "openai" or "perplexity" - determines which API to use
        use_tavily: Whether to use Tavily search for enhanced research (default: True)
    """
    bucket = s3info.get("Bucket") or s3info.get("bucket")
    key = s3info.get("key") or s3info.get("Key")

    if not key or not bucket:
        return {"status": "failed", "error": "Missing S3 bucket or key"}

    if not user_id:
        user_id = str(uuid.uuid4())

    # Download file
    file_obj = s3.get_object(Bucket=bucket, Key=key)
    file_content = file_obj["Body"].read()
    content_type = file_obj.get("ContentType")
    guessed_type, _ = mimetypes.guess_type(key)
    content_type = content_type or guessed_type or "application/pdf"

    SUPPORTED_CONTENT_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/webp"]
    if content_type not in SUPPORTED_CONTENT_TYPES:
        return {"status": "failed", "error": f"Unsupported content type: {content_type}"}

    # TOON: Previous summary with compact formatting
    previous_summary = get_user_summaries(user_id)

    # Extract data
    extracted_data = await extract_data(file_content, content_type)
    if "error" in extracted_data:
        return {"status": "failed", "error": extracted_data["error"]}
    safe_extracted_data = ensure_json_safe(extracted_data)

    # TOON: Compact memory context - last 3 summaries only, truncated
    if previous_summary:
        formatted_prev = "; ".join(
            [f"{item['date']}: {item['summary'][:100]}" for item in previous_summary[-3:]]
        )
        memory_context = f"History: {formatted_prev}"
    else:
        memory_context = "New patient"

    # TOON: Limit extracted data size to 2000 chars
    data_summary = str(safe_extracted_data)[:2000]

    # Initialize Tavily search results
    tavily_context = ""
    
    # If Tavily is enabled and API key is available, perform web search for medical insights
    if use_tavily and os.getenv("TAVILY_API_KEY"):
        print(f"[TAVILY] Tavily search enabled for user_id: {user_id}")
        try:
            from .tavily_client import tavily_search
            
            # Extract abnormal parameters for targeted search
            abnormal_params = []
            if isinstance(safe_extracted_data, dict):
                extracted_params = safe_extracted_data.get('parameters', [])
                for param in extracted_params[:5]:  # Limit to top 5 parameters
                    param_name = param.get('name', '')
                    param_value = param.get('value', '')
                    if param_name and param_value:
                        abnormal_params.append(f"{param_name}: {param_value}")
            
            # Construct Tavily search query for medical insights
            if abnormal_params:
                search_query = f"Medical significance and clinical implications of {', '.join(abnormal_params[:3])}"
                print(f"[TAVILY] Executing search query: {search_query}")
                
                # Perform Tavily search
                search_results = await tavily_search(
                    query=search_query,
                    max_results=3,
                    search_depth="basic",
                    include_answer=True,
                    timeout_s=10.0
                )
                
                print(f"[TAVILY] Search completed. Status: {search_results.get('ok', False)}, Results count: {len(search_results.get('results', []))}")
                
                # Extract relevant information from search results
                if search_results.get("ok") and search_results.get("results"):
                    tavily_snippets = []
                    for idx, result in enumerate(search_results["results"][:3]):
                        content = result.get("content", "")[:200]  # Truncate to 200 chars
                        if content:
                            tavily_snippets.append(content)
                            print(f"[TAVILY] Result {idx+1}: {result.get('title', 'No title')} - {result.get('url', 'No URL')}")
                    
                    if tavily_snippets:
                        tavily_context = "\n\nWeb Research Insights:\n" + "\n- ".join(tavily_snippets)
                        print(f"[TAVILY] Successfully extracted {len(tavily_snippets)} snippets")
                        
                    # Include answer if available
                    if search_results.get("answer"):
                        tavily_context = f"\n\nExpert Summary: {search_results['answer'][:300]}" + tavily_context
                        print(f"[TAVILY] Expert answer included: {search_results['answer'][:100]}...")
                else:
                    print(f"[TAVILY] No valid results returned. Error: {search_results.get('error', 'Unknown')}")
            else:
                print(f"[TAVILY] No abnormal parameters found to search")
                        
        except Exception as e:
            print(f"[TAVILY] Search failed with exception: {type(e).__name__}: {str(e)}")
            import traceback
            print(f"[TAVILY] Traceback: {traceback.format_exc()}")
            tavily_context = ""  # Continue without Tavily on error
    else:
        if not use_tavily:
            print(f"[TAVILY] Tavily search disabled by request parameter")
        elif not os.getenv("TAVILY_API_KEY"):
            print(f"[TAVILY] Tavily API key not found in environment variables")

    # TOON: Compact query with word limit
    query = f"""{memory_context}

Generate concise clinical insights (plain text, under 300 words):

Data: {data_summary}{tavily_context}

Focus on key medical findings with values and clinical significance. Use dashes for lists."""

    # Always use OpenAI (GPT-4o-mini)
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": query}]
    )
    main_insight = response.choices[0].message.content.strip()

    # TOON: Compact summary - 2-3 sentences
    if previous_summary:
        last_summary = previous_summary[-1]['summary'][:150]
        summary_prompt = f"Summarize in 2-3 sentences. Previous: {last_summary}. New: {main_insight[:500]}"
    else:
        summary_prompt = f"Summarize in 2-3 sentences: {main_insight[:500]}"

    # Always use OpenAI (GPT-4o-mini) for summary
    summary_response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": summary_prompt}]
    )
    summary_text = summary_response.choices[0].message.content.strip()

    # Save summary
    save_summary(user_id, summary_text)

    tavily_used = bool(use_tavily and tavily_context and os.getenv("TAVILY_API_KEY"))
    print(f"[TAVILY] Final status - Tavily search used: {tavily_used}")

    result = {
        "status": "success",
        "user_id": user_id,
        "model_used": model,
        "tavily_search_used": tavily_used,
        "final_result": main_insight,
        "summary": summary_text,
        "is_continuation": previous_summary is not None
    }

    return ensure_json_safe(result)