"""LLM-based detection of transcript segments suited to animated diagrams.

Finds the places in a podcast transcript where the speaker walks through a
process, timeline, comparison, or cycle, and asks a Groq Cloud LLM to emit a
constrained graph spec (never code) for each. Output is validated by
``backend.features.diagram.schema`` before it leaves this module.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from groq import Groq

from backend.features.diagram.schema import (
    MAX_LABEL_LENGTH,
    MAX_NODES,
    MIN_DURATION_SECONDS,
    MIN_NODES,
    validate_suggestions,
)

DEFAULT_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = f"""You are an expert motion-graphics designer for podcast videos. Your task is to analyze a transcript and find the few segments where the speaker's explanation would genuinely be clearer with an animated diagram overlaid on the video.

Only suggest a diagram when the speaker explicitly walks through one of:
- "flowchart": a process or sequence of steps
- "timeline": events in chronological order
- "comparison": two or more options or things weighed against each other
- "cycle": a repeating loop or feedback cycle

Guidelines:
1. Be conservative — most segments should get NO diagram. Only suggest one when the speaker explicitly enumerates steps, events, options, or stages.
2. Use between {MIN_NODES} and {MAX_NODES} nodes. Keep node labels under {MAX_LABEL_LENGTH} characters — short phrases, not sentences.
3. Each suggested segment must be at least {MIN_DURATION_SECONDS} seconds long and lie within the transcript timestamps.
4. "reveal_order" lists node ids in the order they should animate onto the screen, matching the order the speaker mentions them.
5. Every edge's "source" and "target" must reference declared node ids.
6. Return ONLY valid JSON without any markdown formatting or code blocks.

Your response must be a JSON object of this exact form:
{{"diagrams": [
  {{
    "start": <segment start in seconds>,
    "end": <segment end in seconds>,
    "diagram_type": "flowchart",
    "title": "<short on-screen title>",
    "transcript_excerpt": "<the sentence(s) the diagram illustrates>",
    "reason": "<why this segment benefits from a diagram>",
    "graph": {{
      "nodes": [{{"id": "n1", "label": "<short label>"}}, {{"id": "n2", "label": "<short label>"}}],
      "edges": [{{"source": "n1", "target": "n2", "label": "<optional edge label>"}}],
      "reveal_order": ["n1", "n2"]
    }}
  }}
]}}

If no segment qualifies, return {{"diagrams": []}}."""


class DiagramDetectorLLM:
    """LLM client for suggesting diagram overlays using Groq Cloud."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        """Initializes the LLM client.

        Args:
            api_key (str, optional): Groq API key. If not provided, reads from the API_KEY env var.
            model (str, optional): Groq model to use. Defaults to "llama-3.3-70b-versatile".
        """
        self.api_key = api_key or os.getenv("API_KEY")
        if not self.api_key:
            raise ValueError(
                "Groq API key must be provided either as argument or API_KEY environment variable"
            )

        self.client = Groq(api_key=self.api_key)
        self.model = model

    def suggest_diagrams(self, transcript: list, additional_context: str = "") -> list:
        """Suggests diagram overlays for the given transcript.

        Args:
            transcript (list): A list of transcript segments with "start", "end", and "text" keys.
            additional_context (str, optional): Additional context or instructions for the LLM.

        Returns:
            list: Validated diagram suggestions sorted by start time. Each is a
                dict with "start", "end", "diagram_type", "title",
                "transcript_excerpt", "reason" and "graph" keys, where "graph"
                holds "nodes", "edges" and "reveal_order".
        """
        transcript_text = self._format_transcript(transcript)

        user_prompt = f"""Here is the podcast transcript to analyze:

{transcript_text}

{additional_context}

Identify the segments that would benefit from an animated diagram and return them as a JSON object with a "diagrams" array."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = json.loads(content)
            suggestions = self._extract_suggestions(result)

            total_duration = transcript[-1]["end"] if transcript else 0.0
            return validate_suggestions(suggestions, total_duration)

        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"Error suggesting diagrams: {e}")

    @staticmethod
    def _extract_suggestions(result) -> list:
        """Extracts the suggestion list from the parsed LLM response.

        Args:
            result: Parsed JSON response (dict or list).

        Returns:
            list: Raw suggestion dicts.

        Raises:
            ValueError: If no list can be found in the response.
        """
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            if isinstance(result.get("diagrams"), list):
                return result["diagrams"]
            for value in result.values():
                if isinstance(value, list):
                    return value
        raise ValueError(f"Unexpected response format: {result}")

    def _format_transcript(self, transcript: list) -> str:
        """Formats the transcript for the LLM prompt.

        Args:
            transcript (list): List of transcript segments.

        Returns:
            str: Formatted transcript string.
        """
        formatted = []
        for segment in transcript:
            formatted.append(
                f"[{segment['start']:.2f}s - {segment['end']:.2f}s] {segment['text']}"
            )
        return "\n".join(formatted)


def suggest_diagrams(
    transcript: list,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    additional_context: str = "",
) -> list:
    """Suggests animated diagram overlays for a video based on its transcript.

    Args:
        transcript (list): A list of transcript segments with "start", "end", and "text" keys.
        api_key (str, optional): Groq API key. If not provided, reads from the API_KEY env var.
        model (str, optional): Groq model to use. Defaults to "llama-3.3-70b-versatile".
        additional_context (str, optional): Additional instructions or context for the LLM.

    Returns:
        list: Validated diagram suggestions sorted by start time.
    """
    llm = DiagramDetectorLLM(api_key=api_key, model=model)
    return llm.suggest_diagrams(transcript, additional_context)
