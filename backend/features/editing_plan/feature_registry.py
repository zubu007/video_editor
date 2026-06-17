"""
Feature registry for available video editing features.
"""

AVAILABLE_FEATURES = {
    "zoom": {
        "name": "zoom",
        "description": "Adds a punch-in zoom effect to emphasize important content (zooms toward the speaker's face, or the frame center if no face is found)",
        "use_case": "Use for key points, important statements, or to add visual interest",
        "parameters": [
            {
                "name": "zoom_level",
                "type": "float",
                "description": "Zoom factor (e.g., 1.2 for 20% zoom)",
                "default": 1.2,
            }
        ],
    },
    "insert_stock_footage": {
        "name": "insert_stock_footage",
        "description": "Inserts B-roll or stock footage to illustrate concepts being discussed",
        "use_case": "Use when speaker describes visual concepts, tells stories, or when visual variety is needed",
        "parameters": [
            {
                "name": "search_query",
                "type": "string",
                "description": "Keywords to search for relevant stock footage",
                "required": True,
            }
        ],
    },
    "text_overlay": {
        "name": "text_overlay",
        "description": "Adds text overlay to highlight key points or quotes",
        "use_case": "Use for memorable quotes, statistics, key takeaways, or definitions",
        "parameters": [
            {
                "name": "text",
                "type": "string",
                "description": "The text to display",
                "required": True,
            },
        ],
    },
    # "transition": {
    #     "name": "transition",
    #     "description": "Adds a transition effect between segments",
    #     "use_case": "Use between topic changes or to smooth scene transitions",
    #     "parameters": [
    #         {
    #             "name": "type",
    #             "type": "string",
    #             "description": "Transition type (fade, crossfade, slide)",
    #             "default": "crossfade"
    #         }
    #     ]
    # },
}


def get_feature_descriptions_for_llm() -> str:
    """
    Generates a formatted string of all available features for the LLM prompt.

    Returns:
        str: Formatted description of all available features.
    """
    descriptions = []
    for feature_id, feature in AVAILABLE_FEATURES.items():
        desc = f"- {feature['name']}: {feature['description']}\n  Use case: {feature['use_case']}"
        if feature["parameters"]:
            params = []
            for param in feature["parameters"]:
                param_desc = f"{param['name']} ({param['type']})"
                if param.get("required"):
                    param_desc += " [required]"
                params.append(param_desc)
            desc += f"\n  Parameters: {', '.join(params)}"
        descriptions.append(desc)

    return "\n\n".join(descriptions)


def validate_feature_name(feature_name: str) -> bool:
    """
    Validates if a feature name exists in the registry.

    Args:
        feature_name (str): The name of the feature to validate.

    Returns:
        bool: True if the feature exists, False otherwise.
    """
    return feature_name in AVAILABLE_FEATURES
