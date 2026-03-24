# ui_agent/views.py
import uuid
import threading
import traceback
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from ui_agent.services.orchestrator import run_pipeline
from ui_agent.services.progress import set_progress, get_progress
from ui_agent.services import image_analyzer
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ui_agent.services.openai_client import chat


RECOMMENDATION_SYSTEM = (
    "You are a biomedical research assistant working with the eDISK knowledge graph. "
    "Given a question and its answer (which contains information about entities, relationships, "
    "and findings from the eDISK graph), generate exactly 3 concise follow-up questions "
    "that a researcher might naturally ask next. "
    "The questions should explore related entities, mechanisms, or associations mentioned in the response. "
    "Return ONLY a JSON array of 3 strings, no other text. "
    "Example: [\"Does X interact with Y?\", \"What genes are associated with Z?\", \"Can A prevent B?\"]"
)


@csrf_exempt
def api_recommendations(request):
    """Generate follow-up question recommendations based on a bot response."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    original_query = (body.get("query") or "").strip()
    response_text = (body.get("response") or "").strip()

    if not response_text:
        return JsonResponse({"recommendations": []})

    user_prompt = (
        f"Original question: {original_query}\n\n"
        f"eDISK response: {response_text}\n\n"
        "Generate 3 follow-up research questions based on the entities and relationships mentioned above."
    )

    try:
        raw = chat(
            [
                {"role": "system", "content": RECOMMENDATION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )

        import re
        # Strip markdown code fences if present
        cleaned = raw.strip().strip("`")
        cleaned = re.sub(r'^json\s*', '', cleaned, flags=re.I)
        recommendations = json.loads(cleaned)

        if not isinstance(recommendations, list):
            recommendations = []

        # Sanitize: keep only strings, max 3
        recommendations = [r for r in recommendations if isinstance(r, str)][:3]

    except Exception as e:
        print(f"[WARN] Recommendations generation failed: {e}")
        recommendations = []

    return JsonResponse({"recommendations": recommendations})
def chat_page(request):
    """渲染主聊天界面"""
    return render(request, "index.html")


@csrf_exempt
def api_chat(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    q = request.POST.get("query", "").strip()
    image_file = request.FILES.get("image")
    if not q and not image_file:
        return JsonResponse({"error": "Empty query"}, status=400)

    image_bytes = None
    if image_file:
        image_bytes = image_file.read()

    run_id = str(uuid.uuid4())[:16]
    set_progress(run_id, "[Task Intake] Request received.")

    def background_task():
        try:
            augmented_query = q
            detected = []

            if image_bytes:
                set_progress(run_id, "[Task Intake] Processing uploaded image...")
                try:
                    detected = image_analyzer.detect_supplement_names(image_bytes)
                except Exception as exc:
                    print(f"[WARN] Image analysis failed: {exc}")
                    detected = []

                augmented_query, detected = image_analyzer.augment_query_with_detections(
                    augmented_query,
                    detected,
                )

                if detected:
                    set_progress(
                        run_id,
                        f"[Task Intake] Image suggests: {', '.join(detected)}.",
                    )
                else:
                    set_progress(
                        run_id,
                        "[Task Intake] Unable to recognise supplement from the image.",
                    )

            if not augmented_query:
                set_progress(run_id, "[FINAL] I couldn't interpret a question from your request.")
                set_progress(run_id, "[DONE]")
                return

            set_progress(run_id, "[1/7] Parsing query...")
            run_pipeline(run_id=run_id, user_query=augmented_query)
        except Exception as e:
            tb = traceback.format_exc()
            print(tb)
            set_progress(run_id, f"[ERROR] {e}")
            set_progress(run_id, "[DONE]")

    threading.Thread(target=background_task, daemon=True).start()
    return JsonResponse({"run_id": run_id})


def api_progress(request, run_id):
    messages = get_progress(run_id)
    finished = any("[DONE]" in m for m in messages)
    return JsonResponse({"messages": messages, "finished": finished})
