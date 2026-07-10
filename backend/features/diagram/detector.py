"""LLM-based detection of transcript segments suited to animated diagrams.

Two-stage pipeline over a podcast transcript:

1. **Detection** — one LLM call over the whole transcript finds the sections
   where the speaker walks through a process, timeline, comparison, or cycle,
   returning each section's timestamps and excerpt.
2. **Design** — one LLM call per detected section turns that explanation into
   a constrained graph spec (nodes, edges, reveal order/timing — never code).

Output is validated by ``backend.features.diagram.schema`` before it leaves
this module, so downstream consumers (the Manim renderer, the API) only ever
see well-formed specs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from groq import Groq

from backend.features.diagram.schema import (
    DIAGRAM_TYPES,
    MAX_LABEL_LENGTH,
    MAX_NODES,
    MIN_DURATION_SECONDS,
    MIN_NODES,
    validate_suggestions,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama-3.3-70b-versatile"

DETECTION_SYSTEM_PROMPT = f"""You are an expert video editor for podcast videos. Your task is to read a full transcript and find the sections where the speaker explains something that would genuinely be clearer with an animated diagram overlaid on the video.

Only flag a section when the speaker explicitly walks through one of:
- "flowchart": a process or sequence of steps
- "timeline": events in chronological order
- "comparison": two or more options or things weighed against each other
- "cycle": a repeating loop or feedback cycle

Guidelines:
1. Be conservative — most of the transcript should get NO section. Only flag a section when the speaker explicitly enumerates steps, events, options, or stages.
2. Each section must be at least {MIN_DURATION_SECONDS} seconds long, lie within the transcript timestamps, and cover the WHOLE explanation from where it starts to where it ends.
3. Sections must not overlap.
4. Return ONLY valid JSON without any markdown formatting or code blocks.

Your response must be a JSON object of this exact form:
{{"sections": [
  {{
    "start": <explanation start in seconds>,
    "end": <explanation end in seconds>,
    "diagram_type": "flowchart",
    "transcript_excerpt": "<the sentence(s) that make up the explanation>",
    "reason": "<why this section benefits from a diagram>"
  }}
]}}

If no section qualifies, return {{"sections": []}}."""

DESIGN_SYSTEM_PROMPT = f"""You are an expert motion-graphics designer. You are given one section of a podcast transcript (with timestamps) in which the speaker explains a {"/".join(DIAGRAM_TYPES)}. Your task is to design the animated diagram that will be overlaid on the video for exactly that section.

Guidelines:
1. Use between {MIN_NODES} and {MAX_NODES} nodes. Keep node labels under {MAX_LABEL_LENGTH} characters — short phrases, not sentences.
2. Each node's "reveal_at" is the timestamp (in seconds, on the transcript's clock) where the speaker first mentions that item — the node animates onto the screen at that moment. It must lie within the section.
3. "reveal_order" lists node ids in the order they should animate onto the screen, matching the order the speaker mentions them.
4. Every edge's "source" and "target" must reference declared node ids.
5. Return ONLY valid JSON without any markdown formatting or code blocks.

Your response must be a JSON object of this exact form:
{{
  "title": "<short on-screen title>",
  "graph": {{
    "nodes": [{{"id": "n1", "label": "<short label>", "reveal_at": <seconds>}}, {{"id": "n2", "label": "<short label>", "reveal_at": <seconds>}}],
    "edges": [{{"source": "n1", "target": "n2", "label": "<optional edge label>"}}],
    "reveal_order": ["n1", "n2"]
  }}
}}"""


class DiagramDetectorLLM:
    """Two-stage LLM client for suggesting diagram overlays using Groq Cloud."""

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

        Runs detection over the whole transcript, then designs one diagram per
        detected section. A section whose design call fails is skipped (logged)
        rather than failing the whole request.

        Args:
            transcript (list): A list of transcript segments with "start", "end", and "text" keys.
            additional_context (str, optional): Additional context or instructions for the LLM.

        Returns:
            list: Validated diagram suggestions sorted by start time. Each is a
                dict with "start", "end", "diagram_type", "title",
                "transcript_excerpt", "reason" and "graph" keys, where "graph"
                holds "nodes" (with optional "reveal_at" offsets relative to
                the segment start), "edges" and "reveal_order".
        """
        sections = self.detect_sections(transcript, additional_context)

        suggestions = []
        for section in sections:
            try:
                suggestions.append(self.design_diagram(transcript, section))
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "Skipping diagram design for section %s-%s: %s",
                    section.get("start"),
                    section.get("end"),
                    exc,
                )

        total_duration = transcript[-1]["end"] if transcript else 0.0
        return validate_suggestions(suggestions, total_duration)

    def detect_sections(self, transcript: list, additional_context: str = "") -> list:
        """Stage 1: finds explanation sections worth a diagram.

        Args:
            transcript (list): Transcript segments with "start", "end", "text".
            additional_context (str, optional): Extra instructions for the LLM.

        Returns:
            list: Raw section dicts with "start", "end", "diagram_type",
                "transcript_excerpt" and "reason" keys.
        """
        transcript_text = self._format_transcript(transcript)

        user_prompt = f"""Here is the podcast transcript to analyze:

{transcript_text}

{additional_context}

Identify the explanation sections that would benefit from an animated diagram and return them as a JSON object with a "sections" array."""

        result = self._complete_json(DETECTION_SYSTEM_PROMPT, user_prompt)
        return self._extract_list(result, "sections")

    def design_diagram(self, transcript: list, section: dict) -> dict:
        """Stage 2: designs the diagram for one detected section.

        Args:
            transcript (list): Full transcript segments with "start", "end", "text".
            section (dict): One section from :meth:`detect_sections`.

        Returns:
            dict: A raw suggestion dict (section fields + "title" + "graph")
                with node "reveal_at" converted to offsets relative to the
                section start, ready for schema validation.

        Raises:
            ValueError: If the section lacks numeric timestamps or the LLM
                response cannot be parsed.
        """
        try:
            start = float(section["start"])
            end = float(section["end"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("section needs numeric 'start' and 'end'")

        section_lines = self._format_transcript(
            [seg for seg in transcript if seg["end"] > start and seg["start"] < end]
        )
        excerpt = str(section.get("transcript_excerpt") or "").strip()

        user_prompt = f"""The section runs from {start:.2f}s to {end:.2f}s. The speaker explains a {section.get("diagram_type", "flowchart")}.

Transcript of the section (with timestamps):

{section_lines or excerpt}

Design the diagram for this section and return it as a JSON object with "title" and "graph" keys."""

        result = self._complete_json(DESIGN_SYSTEM_PROMPT, user_prompt)
        if not isinstance(result, dict):
            raise ValueError(f"Unexpected design response format: {result}")

        graph = result.get("graph") if isinstance(result.get("graph"), dict) else result

        # The design prompt asks for reveal timestamps on the transcript's
        # clock; downstream (schema, renderer) they are offsets from the
        # segment start.
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("reveal_at") is not None:
                try:
                    node["reveal_at"] = max(0.0, float(node["reveal_at"]) - start)
                except (TypeError, ValueError):
                    node.pop("reveal_at", None)

        return {
            "start": start,
            "end": end,
            "diagram_type": section.get("diagram_type"),
            "transcript_excerpt": excerpt,
            "reason": str(section.get("reason") or "").strip(),
            "title": result.get("title"),
            "graph": graph,
        }

    def _complete_json(self, system_prompt: str, user_prompt: str) -> dict | list:
        """Runs one JSON-mode completion and parses the response.

        Args:
            system_prompt (str): System prompt for the call.
            user_prompt (str): User prompt for the call.

        Returns:
            dict | list: Parsed JSON response.

        Raises:
            ValueError: If the response is not valid JSON.
            RuntimeError: If the API call itself fails.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise RuntimeError(f"Error calling Groq: {e}")

        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")

    @staticmethod
    def _extract_list(result, key: str) -> list:
        """Extracts the list under ``key`` from the parsed LLM response.

        Args:
            result: Parsed JSON response (dict or list).
            key: Preferred key holding the list.

        Returns:
            list: Extracted items.

        Raises:
            ValueError: If no list can be found in the response.
        """
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            if isinstance(result.get(key), list):
                return result[key]
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
