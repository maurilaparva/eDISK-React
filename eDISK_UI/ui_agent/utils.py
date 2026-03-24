"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: utils.py
@Time: 7/29/25; 4:02 PM
"""
import openai
import json
from django.conf import settings

client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)


def summarize_results(parsed, results):
    if not results or all(len(r.get("result", [])) == 0 for r in results):
        return "No relevant information found in eDISK."

    prompt = f"""
    You are an AI assistant for biomedical knowledge retrieval, working with a Neo4j knowledge graph called eDISK.
    
    The user asked a question, which was parsed into this structure:
    {json.dumps(parsed, indent=2)}
    
    The query returned the following structured graph results:
    {json.dumps(results, indent=2)}
    
    Your task is to write a fluent, natural-sounding paragraph that explains the retrieved information **clearly and factually**, as if you were speaking to a researcher or practitioner.
    
    **Instructions:**
    - Write in clear, natural English. Keep the tone professional, helpful, and objective.
    - Do NOT include subjective evaluations like "this is not supported by strong evidence" or "further research is needed".
    - If entity nodes include properties such as Name, Background, Mechanism_of_action, or Source_material, incorporate them smoothly into the narrative.
    - If a relationship includes fields like Type, Sentence, PubMed_ID, or Source, include them naturally where appropriate.
    - Do NOT mention missing fields.
    - If multiple relationships or triples are present, summarize them logically within the paragraph.
    
    Begin your response directly. Do NOT include bullet points or lists. Use natural transitions. Avoid repeating the query structure. Focus on answering like a smart assistant.
    """

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
    )

    return completion.choices[0].message.content.strip()