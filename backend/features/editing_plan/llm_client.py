"""
LLM client for generating editing decisions using the configured LLM provider.
"""

import json
from typing import Optional

from backend.features.editing_plan.feature_registry import (
    get_feature_descriptions_for_llm,
)
from backend.features.llm import DEFAULT_MODEL, create_chat_client


class EditingPlanLLM:
    """
    LLM client for generating editing plans (Groq Cloud by default, or any
    OpenAI-compatible provider via a custom base URL).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        base_url: Optional[str] = None,
    ):
        """
        Initializes the LLM client.

        Args:
            api_key (str, optional): Provider API key. If not provided, reads from the API_KEY env var.
            model (str, optional): Model to use. Defaults to "llama-3.3-70b-versatile".
            base_url (str, optional): OpenAI-compatible base URL for a custom
                provider. If not provided, reads from the API_BASE_URL env var;
                unset means Groq Cloud.
        """
        self.client = create_chat_client(api_key=api_key, base_url=base_url)
        self.model = model

    def generate_editing_plan(
        self, transcript: list, additional_context: str = ""
    ) -> list:
        """
        Generates an editing plan for the given transcript using LLM.

        Args:
            transcript (list): A list of transcript segments with "start", "end", and "text" keys.
            additional_context (str, optional): Additional context or instructions for the LLM.

        Returns:
            list: A list of editing decisions. Each decision is a dictionary with:
                  - "start" (float): Start time in seconds
                  - "end" (float): End time in seconds
                  - "feature" (str): Name of the feature to apply
                  - "parameters" (dict, optional): Parameters for the feature
                  - "reason" (str, optional): Explanation for this editing decision
        """
        # Build the system prompt
        feature_descriptions = get_feature_descriptions_for_llm()

        system_prompt = f"""You are an expert video editor for podcast content. Your task is to analyze a transcript and create an editing plan that will make the video more engaging and professional.

Available editing features:
{feature_descriptions}

Guidelines:
1. Analyze the content and context of each sentence
2. Select appropriate features that will enhance viewer engagement
3. Don't overuse effects - be strategic and purposeful
4. Prioritize features that add value (text overlays for key points, stock footage for visual concepts, zoom for emphasis)
5. Consider pacing - use speed_up for less critical content
6. Return ONLY valid JSON without any markdown formatting or code blocks

IMPORTANT - Stock Footage Requirements:
- When using "insert_stock_footage" feature, you MUST provide a "search_query" parameter
- The search_query should be a concise, descriptive phrase (2-4 words) that captures the visual concept
- Examples: "ocean waves sunset", "neural network visualization", "city traffic timelapse", "forest nature"
- The search query will be used to download appropriate stock footage from Pexels API
- Also provide a "media_type" parameter: "video" for a short clip, "image" for a still photo
- Mix both media types across the plan (roughly half and half): use "image" for static
  subjects (objects, places, portraits, products), "video" for motion, actions, or processes
- B-roll must stay short to hold viewer attention: a "video" span may last at most 5 seconds
  and an "image" span at most 3 seconds. Never exceed these limits — if the concept runs
  longer, still end the B-roll at the limit (spans that exceed it will be cut down to it)

Your response must be a valid JSON array of editing decisions. Each decision must have:
- "start": timestamp in seconds (float)
- "end": timestamp in seconds (float)
- "feature": name of the feature (must match exactly from the available features)
- "parameters": object with feature parameters (required for some features like insert_stock_footage)
- "reason": brief explanation of why this feature is appropriate (optional)"""

        # Build the transcript text
        transcript_text = self._format_transcript(transcript)

        user_prompt = f"""Here is the podcast transcript to analyze:

{transcript_text}

{additional_context}

Generate an editing plan as a JSON array. Each element should specify the start time, end time, feature to use, and any parameters."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            # Parse the JSON response
            result = json.loads(content)

            # Handle both {"editing_plan": [...]} and direct array formats
            if isinstance(result, dict) and "editing_plan" in result:
                editing_plan = result["editing_plan"]
            elif isinstance(result, dict) and "decisions" in result:
                editing_plan = result["decisions"]
            elif isinstance(result, list):
                editing_plan = result
            else:
                # Try to find the first list in the result
                for value in result.values():
                    if isinstance(value, list):
                        editing_plan = value
                        break
                else:
                    raise ValueError(f"Unexpected response format: {result}")

            # Validate and clean the editing plan
            validated_plan = self._validate_editing_plan(editing_plan, transcript)

            return validated_plan

        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"Error generating editing plan: {e}")

    def _format_transcript(self, transcript: list) -> str:
        """
        Formats the transcript for the LLM prompt.

        Args:
            transcript (list): List of transcript segments.

        Returns:
            str: Formatted transcript string.
        """
        formatted = []
        for i, segment in enumerate(transcript):
            formatted.append(
                f"[{segment['start']:.2f}s - {segment['end']:.2f}s] {segment['text']}"
            )
        return "\n".join(formatted)

    def _validate_editing_plan(self, editing_plan: list, transcript: list) -> list:
        """
        Validates and cleans the editing plan.

        Args:
            editing_plan (list): Raw editing plan from LLM.
            transcript (list): Original transcript for validation.

        Returns:
            list: Validated and cleaned editing plan.
        """
        from backend.features.editing_plan.feature_registry import (
            AVAILABLE_FEATURES,
            clamp_stock_footage_end,
            normalize_stock_media_type,
            validate_feature_name,
        )

        validated = []
        total_duration = transcript[-1]["end"] if transcript else 0

        for decision in editing_plan:
            # Ensure required fields exist
            if not all(key in decision for key in ["start", "end", "feature"]):
                continue

            # Validate timestamps
            start = float(decision["start"])
            end = float(decision["end"])

            if start < 0 or end > total_duration or start >= end:
                continue

            # Validate feature name
            if not validate_feature_name(decision["feature"]):
                continue

            # Ensure parameters is a dict
            if "parameters" not in decision:
                decision["parameters"] = {}
            elif not isinstance(decision["parameters"], dict):
                decision["parameters"] = {}

            # Validate required parameters for specific features
            feature_name = decision["feature"]
            feature_def = AVAILABLE_FEATURES.get(feature_name)

            if feature_def:
                missing_required_parameter = False

                # Check for required parameters
                for param in feature_def.get("parameters", []):
                    if (
                        param.get("required")
                        and param["name"] not in decision["parameters"]
                    ):
                        # Skip this decision if required parameter is missing
                        print(
                            f"Warning: Skipping {feature_name} at {start:.2f}s - missing required parameter '{param['name']}'"
                        )
                        missing_required_parameter = True
                        break

                if missing_required_parameter:
                    continue

                # Special validation for stock footage search_query
                if feature_name == "insert_stock_footage":
                    search_query = (
                        decision["parameters"].get("search_query", "").strip()
                    )
                    if not search_query:
                        print(
                            f"Warning: Skipping insert_stock_footage at {start:.2f}s - empty search_query"
                        )
                        continue

                    # Normalize the media type and enforce the attention-span
                    # cap (5s video / 3s still image) on the span duration.
                    media_type = normalize_stock_media_type(
                        decision["parameters"].get("media_type")
                    )
                    decision["parameters"]["media_type"] = media_type
                    clamped_end = clamp_stock_footage_end(start, end, media_type)
                    if clamped_end < end:
                        print(
                            f"Warning: Trimming insert_stock_footage at {start:.2f}s "
                            f"from {end - start:.2f}s to {clamped_end - start:.2f}s "
                            f"({media_type} attention limit)"
                        )
                        end = clamped_end

            validated.append(
                {
                    "start": start,
                    "end": end,
                    "feature": decision["feature"],
                    "parameters": decision["parameters"],
                    "reason": decision.get("reason", ""),
                }
            )

        return validated
