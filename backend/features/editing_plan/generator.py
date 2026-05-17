"""
Main module for generating editing plans from transcripts.
"""

import json
from typing import Optional

from backend.features.editing_plan.llm_client import EditingPlanLLM


def generate_editing_plan(
    transcript: list,
    api_key: Optional[str] = None,
    model: str = "gpt-4",
    additional_context: str = "",
    output_file: Optional[str] = None
) -> list:
    """
    Generates an editing plan for a video based on its transcript.

    Args:
        transcript (list): A list of transcript segments with "start", "end", and "text" keys.
        api_key (str, optional): OpenAI API key. If not provided, reads from OPENAI_API_KEY env var.
        model (str, optional): OpenAI model to use. Defaults to "gpt-4".
        additional_context (str, optional): Additional instructions or context for the LLM.
        output_file (str, optional): Path to save the editing plan as JSON.

    Returns:
        list: A list of editing decisions with timestamps and features to apply.

    Example:
        >>> transcript = [
        ...     {"start": 0.0, "end": 3.5, "text": "Welcome to this podcast about AI."},
        ...     {"start": 3.5, "end": 8.2, "text": "Today we'll discuss neural networks."}
        ... ]
        >>> plan = generate_editing_plan(transcript)
        >>> print(plan)
        [
            {
                "start": 0.0,
                "end": 3.5,
                "feature": "text_overlay",
                "parameters": {"text": "AI Podcast", "style": "title"},
                "reason": "Opening statement - add title overlay"
            },
            ...
        ]
    """
    # Initialize the LLM client
    llm = EditingPlanLLM(api_key=api_key, model=model)
    
    # Generate the editing plan
    editing_plan = llm.generate_editing_plan(transcript, additional_context)
    
    # Save to file if requested
    if output_file:
        save_editing_plan(editing_plan, output_file)
    
    return editing_plan


def save_editing_plan(editing_plan: list, output_file: str) -> None:
    """
    Saves the editing plan to a JSON file.

    Args:
        editing_plan (list): The editing plan to save.
        output_file (str): Path to the output JSON file.
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(editing_plan, f, indent=2, ensure_ascii=False)
    print(f"Editing plan saved to {output_file}")


def load_editing_plan(input_file: str) -> list:
    """
    Loads an editing plan from a JSON file.

    Args:
        input_file (str): Path to the JSON file.

    Returns:
        list: The loaded editing plan.
    """
    with open(input_file, 'r', encoding='utf-8') as f:
        editing_plan = json.load(f)
    return editing_plan


def print_editing_plan(editing_plan: list) -> None:
    """
    Prints the editing plan in a human-readable format.

    Args:
        editing_plan (list): The editing plan to print.
    """
    print("\n" + "="*80)
    print("EDITING PLAN")
    print("="*80 + "\n")
    
    for i, decision in enumerate(editing_plan, 1):
        print(f"{i}. [{decision['start']:.2f}s - {decision['end']:.2f}s]")
        print(f"   Feature: {decision['feature']}")
        
        if decision.get('parameters'):
            print(f"   Parameters: {decision['parameters']}")
        
        if decision.get('reason'):
            print(f"   Reason: {decision['reason']}")
        
        print()
    
    print("="*80)


def merge_editing_plans(plans: list) -> list:
    """
    Merges multiple editing plans into one, sorting by start time.

    Args:
        plans (list): A list of editing plans to merge.

    Returns:
        list: A single merged editing plan sorted by start time.
    """
    merged = []
    for plan in plans:
        merged.extend(plan)
    
    # Sort by start time
    merged.sort(key=lambda x: x['start'])
    
    return merged


def filter_editing_plan_by_feature(editing_plan: list, feature_names: list) -> list:
    """
    Filters an editing plan to only include specific features.

    Args:
        editing_plan (list): The editing plan to filter.
        feature_names (list): List of feature names to keep.

    Returns:
        list: Filtered editing plan.
    """
    return [
        decision for decision in editing_plan
        if decision['feature'] in feature_names
    ]
