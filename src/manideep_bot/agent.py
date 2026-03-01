"""One-shot reply: persona + solved tickets + skills → Anthropic (Claude) or Gemini."""
from typing import Literal, Optional
from pydantic import BaseModel

from .config import Config
from .prompts import get_system_prompt
from .retriever import find_relevant, format_relevant_for_prompt


class TicketSuggestionResponse(BaseModel):
    """Structured response from AI for ticket suggestions."""
    analysis: str  # AI's analysis of the issue
    approach: str  # Step-by-step approach
    skill_name: str  # e.g., "order-trace-debugger"
    confidence: Literal["high", "medium", "low"]
    missing_info: Optional[list[str]] = None
    recommendation: Literal["proceed", "need_more_info", "not_applicable"]


def _call_anthropic(user_content: str, system: str, config: Config) -> TicketSuggestionResponse:
    api_key = config.anthropic.api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Set it in env or config, or use Gemini (AI_PROVIDER=gemini and GEMINI_API_KEY=...).")
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("Install anthropic: pip install anthropic")

    client = Anthropic(api_key=api_key)

    # Use structured outputs with JSON schema + prompt caching
    resp = client.messages.create(
        model=config.anthropic.model,
        max_tokens=config.anthropic.max_tokens,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"}  # Cache system prompt for 5 minutes
            }
        ],
        messages=[{
            "role": "user",
            "content": user_content
        }]
    )

    # Extract text from response
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text += block.text

    # Parse as JSON and validate with Pydantic
    try:
        result = TicketSuggestionResponse.model_validate_json(text)
        return result
    except Exception:
        # Fallback: if JSON parsing fails, return a basic structure
        return TicketSuggestionResponse(
            analysis="Could not parse structured response",
            approach=text[:500],
            skill_name="",
            confidence="low",
            recommendation="not_applicable"
        )


def _call_gemini_rest(api_key: str, model: str, system: str, user_content: str, max_tokens: int) -> str:
    """Direct REST call to Gemini API (fallback when SDK model names 404)."""
    try:
        import requests
    except ImportError:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user_content}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = requests.post(url, params={"key": api_key}, json=payload, timeout=60)
    if r.status_code != 200:
        return ""
    data = r.json()
    for c in data.get("candidates", []):
        for p in c.get("content", {}).get("parts", []):
            if "text" in p:
                return p["text"].strip()
    return ""


def _call_gemini(user_content: str, system: str, config: Config) -> str:
    api_key = config.gemini.api_key
    if not api_key:
        return "Error: GEMINI_API_KEY not set. Set it in env or config (or use AI_PROVIDER=anthropic with ANTHROPIC_API_KEY)."
    model_name = (config.gemini.model or "gemini-2.5-flash").strip()
    max_tokens = config.gemini.max_tokens

    # 1) Try SDK with multiple model names
    try:
        import google.generativeai as genai
    except ImportError:
        pass
    else:
        genai.configure(api_key=api_key)
        gen_config = genai.types.GenerationConfig(max_output_tokens=max_tokens)
        fallbacks = [model_name, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-pro-latest"]
        seen = set()
        for try_model in fallbacks:
            if not try_model or try_model in seen:
                continue
            seen.add(try_model)
            try:
                model = genai.GenerativeModel(try_model, system_instruction=system)
                resp = model.generate_content(user_content, generation_config=gen_config)
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                err_str = str(e).lower()
                if "404" in err_str or "not found" in err_str:
                    continue
                return f"Error: {e}"

    # 2) Fallback: direct REST (v1beta) with common model IDs
    for rest_model in [model_name, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-pro-latest"]:
        if not rest_model:
            continue
        out = _call_gemini_rest(api_key, rest_model, system, user_content, max_tokens)
        if out:
            return out

    return (
        "Error: No Gemini model worked (404). Check your key at https://aistudio.google.com/apikey and "
        "in scripts/.env set GEMINI_MODEL= to a model from https://ai.google.dev/gemini-api/docs/models"
    )


def reply(user_message: str, config: Config) -> str:
    """Understand the issue, find relevant past solved tickets, then get one reply from AI (Claude or Gemini)."""
    system = get_system_prompt(config)
    top_k = getattr(config.retriever, "top_k", 12) if getattr(config, "retriever", None) else 12
    relevant = find_relevant(user_message.strip(), config, top_k=top_k)
    relevant_block = format_relevant_for_prompt(relevant, max_items=min(10, top_k))

    # Enhanced user prompt with chain-of-thought guidance
    user_content = (
        f"Current issue (title/description):\n\n{user_message.strip()}\n\n"
        "---\n"
        f"Relevant past tickets (use these to suggest a similar approach):\n\n{relevant_block}\n\n"
        "---\n"
        "Think step-by-step:\n"
        "1. What type of issue is this? (order trace, gc redemption, booking, cancellation, etc.)\n"
        "2. Which past ticket is most similar?\n"
        "3. What skill was used for similar issues?\n"
        "4. What information is needed to run the skill?\n"
        "5. Based on the above, provide your response in JSON format with:\n"
        "   - analysis: your analysis of the issue\n"
        "   - approach: step-by-step approach\n"
        "   - skill_name: the skill to run (e.g., 'order-trace-debugger')\n"
        "   - confidence: 'high', 'medium', or 'low'\n"
        "   - missing_info: list of missing information (if any)\n"
        "   - recommendation: 'proceed', 'need_more_info', or 'not_applicable'\n"
    )

    provider = (getattr(config, "ai_provider", None) or "anthropic").lower().strip()

    if provider == "gemini":
        # Gemini doesn't support native structured outputs, but may return JSON
        gemini_response = _call_gemini(user_content, system, config)

        # Try to parse as JSON and format nicely
        try:
            import json
            import re

            # Extract JSON from markdown code fences if present
            cleaned = gemini_response.strip()
            # Remove ```json ... ``` or ``` ... ``` wrapping
            if cleaned.startswith("```"):
                # Find content between ``` markers
                match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()

            # Check if response is JSON
            if cleaned.startswith("{"):
                parsed = json.loads(cleaned)
                structured_response = TicketSuggestionResponse(**parsed)

                # Format into user-friendly text
                formatted_text = (
                    f"**Analysis:** {structured_response.analysis}\n\n"
                    f"**Approach:**\n{structured_response.approach}\n\n"
                    f"**Skill to run:** {structured_response.skill_name}\n"
                    f"**Confidence:** {structured_response.confidence}\n"
                )

                if structured_response.missing_info:
                    formatted_text += f"\n**Missing information:**\n- " + "\n- ".join(structured_response.missing_info) + "\n"

                if structured_response.recommendation == "proceed":
                    formatted_text += "\n\nReply **Yes** to run the skill, or **No** to cancel."
                elif structured_response.recommendation == "need_more_info":
                    formatted_text += "\n\nPlease provide the missing information listed above."
                else:
                    formatted_text += "\n\nThis issue may not be applicable for automated resolution."

                return formatted_text
            else:
                # Not JSON, return as-is
                return gemini_response
        except Exception as e:
            # Parsing failed, log and return text as-is
            import logging
            logging.getLogger(__name__).debug(f"Failed to parse Gemini JSON response: {e}")
            return gemini_response

    # Claude with structured outputs
    try:
        structured_response = _call_anthropic(user_content, system, config)

        # Format structured response into user-friendly text
        formatted_text = (
            f"**Analysis:** {structured_response.analysis}\n\n"
            f"**Approach:**\n{structured_response.approach}\n\n"
            f"**Skill to run:** {structured_response.skill_name}\n"
            f"**Confidence:** {structured_response.confidence}\n"
        )

        if structured_response.missing_info:
            formatted_text += f"\n**Missing information:**\n- " + "\n- ".join(structured_response.missing_info) + "\n"

        if structured_response.recommendation == "proceed":
            formatted_text += "\n\nReply **Yes** to run the skill, or **No** to cancel."
        elif structured_response.recommendation == "need_more_info":
            formatted_text += "\n\nPlease provide the missing information listed above."
        else:
            formatted_text += "\n\nThis issue may not be applicable for automated resolution."

        return formatted_text

    except Exception as e:
        # Fallback to text-based if structured output fails
        import logging
        logging.getLogger(__name__).error(f"Structured output failed: {e}, falling back to text")
        return _call_gemini(user_content, system, config)
