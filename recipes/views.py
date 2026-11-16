
import json
import uuid

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from dotenv import dotenv_values

from .catalog import CATEGORIES, PRODUCTS, build_products
from .models import SavedRecipe


LANGUAGES = ("kk", "ru")
DEFAULT_LANGUAGE = "kk"
MINUTES_CHOICES = ("15", "30", "60")
DEFAULT_MINUTES = "30"

MESSAGES = {
    "kk": {
        "minutes_invalid": "Дайындау уақытын 15, 30 немесе 60 минут арасынан таңдаңыз.",
        "key_missing": ".env файлына GEMINI_API_KEY мәнін енгізіңіз (manage.py жанындағы файл).",
        "api_failed": "Рецептті жасау мүмкін болмады. Кейінірек қайталап көріңіз.",
        "empty": "Қызметтен бос жауап келді. Қайтадан көріңіз.",
        "rate_limit": "Gemini сұраныс лимиті аяқталды. Кейінірек қайталап көріңіз.",
    },
    "ru": {
        "minutes_invalid": "Выберите время приготовления: 15, 30 или 60 минут.",
        "key_missing": "Укажите значение GEMINI_API_KEY в файле .env (рядом с manage.py).",
        "api_failed": "Не удалось создать рецепт. Попробуйте позже.",
        "empty": "Сервис вернул пустой ответ. Попробуйте ещё раз.",
        "rate_limit": "Лимит запросов Gemini исчерпан. Попробуйте позже.",
    },
}

LANGUAGE_NAMES = {
    "kk": "Kazakh",
    "ru": "Russian",
}

VALID_PRODUCT_IDS = {product["id"] for product in PRODUCTS}


def get_language(value):
    if value in LANGUAGES:
        return value
    return DEFAULT_LANGUAGE


def valid_selected_ids(raw_ids):
    return [
        product_id
        for product_id in dict.fromkeys(raw_ids)
        if product_id in VALID_PRODUCT_IDS
    ]


def build_memory_context():
    previous = list(SavedRecipe.objects.all()[:6])
    previous.reverse()

    if not previous:
        return "No previous requests yet."

    blocks = []

    for item in previous:
        blocks.append(
            "Previous request:\n"
            f"Products: {item.products}\n"
            f"Time: {item.minutes} minutes\n"
            f"Vegetarian: {'yes' if item.vegetarian else 'no'}\n"
            f"Assistant answer: {item.recipe}"
        )

    return "\n\n".join(blocks)


def build_prompt(products, minutes, vegetarian, language):
    veg_text = (
        "The recipe must be strictly vegetarian "
        "(no meat, poultry, fish or seafood)."
        if vegetarian
        else "The recipe does not have to be vegetarian."
    )

    memory = build_memory_context()

    return (
        "You are SmartChef, a helpful cooking assistant "
        "with conversation memory.\n"
        "Use previous requests only when they are useful "
        "for the current answer. "
        "Do not blindly repeat old recipes. "
        "Notice the user's earlier preferences and choices.\n\n"
        f"MEMORY:\n{memory}\n\n"
        "CURRENT REQUEST:\n"
        f"Write the entire answer in {LANGUAGE_NAMES[language]}.\n"
        f"Available products: {products}\n"
        f"Maximum cooking time: {minutes} minutes.\n"
        f"{veg_text}\n"
        "Give exactly one recipe in plain text with these parts: "
        "title, cooking time, ingredients, numbered steps, and a tip. "
        "Do not use Markdown tables or code blocks."
    )


def index(request):
    language = get_language(
        request.GET.get("language", DEFAULT_LANGUAGE)
    )

    context = {
        "language": language,
        "products": "",
        "minutes": DEFAULT_MINUTES,
        "vegetarian": False,
        "recipe": "",
        "error": "",
        "can_save": False,
        "history": SavedRecipe.objects.all()[:20],
        "categories": CATEGORIES,
        "catalog_products": PRODUCTS,
        "selected_products": [],
        "catalog_data": {
            "categories": CATEGORIES,
            "products": PRODUCTS,
            "language": language,
        },
    }

    if request.method != "POST":
        return render(request, "recipes/index.html", context)

    language = get_language(
        request.POST.get("language", DEFAULT_LANGUAGE)
    )
    products = request.POST.get("products", "")
    minutes = request.POST.get("minutes", DEFAULT_MINUTES)
    vegetarian = request.POST.get("vegetarian") == "1"
    action = request.POST.get("action")
    raw_ids = request.POST.getlist("selected_products")

    selected_products = valid_selected_ids(raw_ids)

    context.update({
        "language": language,
        "products": products,
        "minutes": (
            minutes if minutes in MINUTES_CHOICES
            else DEFAULT_MINUTES
        ),
        "vegetarian": vegetarian,
        "selected_products": selected_products,
        "catalog_data": {
            "categories": CATEGORIES,
            "products": PRODUCTS,
            "language": language,
        },
    })

    if action in ("generate", "language"):
        request.session.pop("smartchef_draft", None)

    if action != "generate":
        return render(request, "recipes/index.html", context)

    messages = MESSAGES[language]

    # Анықтамалықтағы өнім атауларын тек сервер анықтайды.
    # Жарамсыз ID болса, Gemini сұранысы жіберілмейді.
    try:
        selected_products, combined = build_products(
            raw_ids,
            products,
            language,
        )
    except ValueError as exc:
        context["error"] = str(exc)
        return render(request, "recipes/index.html", context)

    context["selected_products"] = selected_products

    if minutes not in MINUTES_CHOICES:
        context["error"] = messages["minutes_invalid"]
        return render(request, "recipes/index.html", context)

    config = dotenv_values(settings.BASE_DIR / ".env")
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    model = (
        (config.get("GEMINI_MODEL") or "").strip()
        or "gemini-3.8-flash"
    )

    if not api_key or api_key == "PASTE_YOUR_KEY_HERE":
        context["error"] = messages["key_missing"]
        return render(request, "recipes/index.html", context)

    prompt = build_prompt(
        combined,
        minutes,
        vegetarian,
        language,
    )

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        interaction = client.interactions.create(
            model=model,
            input=prompt,
        )

        recipe = interaction.output_text or ""

    except Exception as exc:
        error_type = type(exc).__name__

        print("=" * 60)
        print("GEMINI ERROR")
        print("ERROR TYPE:", error_type)
        print("ERROR DETAILS:", str(exc))
        print("=" * 60)

        if error_type == "RateLimitError":
            context["error"] = messages["rate_limit"]
        else:
            context["error"] = messages["api_failed"]

        return render(request, "recipes/index.html", context)

    recipe = str(recipe).strip()

    if not recipe:
        context["error"] = messages["empty"]
        return render(request, "recipes/index.html", context)

    request.session["smartchef_draft"] = {
        "token": str(uuid.uuid4()),
        "products": combined,
        "recipe": recipe,
        "language": language,
        "minutes": int(minutes),
        "vegetarian": vegetarian,
    }

    context["recipe"] = recipe
    context["can_save"] = True

    return render(request, "recipes/index.html", context)


@require_POST
def save_recipe(request):
    draft = request.session.get("smartchef_draft")

    if not draft:
        return redirect("recipes:index")

    SavedRecipe.objects.get_or_create(
        token=draft["token"],
        defaults={
            "products": draft["products"],
            "recipe": draft["recipe"],
            "language": draft["language"],
            "minutes": draft["minutes"],
            "vegetarian": draft["vegetarian"],
        },
    )

    language = get_language(draft["language"])
    return redirect(f"/saved/?language={language}")


def saved_recipes(request):
    language = get_language(
        request.GET.get("language", DEFAULT_LANGUAGE)
    )

    items = list(SavedRecipe.objects.all())
    recipe_cards = [
        {"item": item, "suggestion": request.session.get(_change_session_key(item.token))}
        for item in items
    ]
    error = request.session.pop("smartchef_change_error", "")
    return render(
        request,
        "recipes/saved.html",
        {
            "saved_recipes": items,
            "recipe_cards": recipe_cards,
            "language": language,
            "change_error": error,
        },
    )


CHANGE_REQUEST_MAX_LENGTH = 1000


def _change_session_key(token):
    return f"smartchef_change_{token}"


def _get_gemini_settings():
    config = dotenv_values(settings.BASE_DIR / ".env")
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    model = (config.get("GEMINI_MODEL") or "").strip() or "gemini-3.8-flash"
    return api_key, model


def _parse_change_response(raw_text):
    """Accept only the documented JSON object; never treat arbitrary prose as a recipe."""
    text = str(raw_text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    data = json.loads(text.strip())
    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object")
    recipe = data.get("recipe")
    changes = data.get("changes", [])
    if not isinstance(recipe, str) or not recipe.strip() or len(recipe) > 20000:
        raise ValueError("Invalid recipe field")
    if not isinstance(changes, list) or len(changes) > 20 or any(not isinstance(x, str) for x in changes):
        raise ValueError("Invalid changes field")
    clean_changes = [item.strip()[:300] for item in changes if item.strip()]
    return {"recipe": recipe.strip(), "changes": clean_changes}


@require_POST
def request_recipe_change(request, token):
    item = get_object_or_404(SavedRecipe, token=token)
    language = get_language(request.POST.get("language", item.language))
    instruction = request.POST.get("instruction", "").strip()
    if not instruction or len(instruction) > CHANGE_REQUEST_MAX_LENGTH:
        request.session["smartchef_change_error"] = (
            "Өзгерту сұрауы 1–1000 таңба болуы керек." if language == "kk"
            else "Запрос должен содержать от 1 до 1000 символов."
        )
        return redirect(f"/saved/?language={language}")

    api_key, model = _get_gemini_settings()
    if not api_key or api_key == "PASTE_YOUR_KEY_HERE":
        request.session["smartchef_change_error"] = (
            "GEMINI_API_KEY бапталмаған." if language == "kk"
            else "GEMINI_API_KEY не настроен."
        )
        return redirect(f"/saved/?language={language}")

    prompt = (
        "You are SmartChef. Modify ONLY the supplied saved recipe according to the user's request. "
        "Preserve its existing ingredients and constraints unless the user explicitly asks to change them. "
        "Return valid JSON only, with exactly these fields: "
        '{"recipe":"complete revised recipe as plain text","changes":["short change description"]}. '
        "Do not wrap JSON in markdown. The entire recipe and change descriptions must be in "
        f"{LANGUAGE_NAMES[language]}.\n\n"
        f"SAVED RECIPE:\n{item.recipe}\n\nUSER CHANGE REQUEST:\n{instruction}"
    )
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        interaction = client.interactions.create(model=model, input=prompt)
        suggestion = _parse_change_response(interaction.output_text)
    except Exception as exc:
        # Keep provider details and secrets out of the page/session.
        print("SMARTCHEF CHANGE ERROR:", type(exc).__name__)
        request.session["smartchef_change_error"] = (
            "AI ұсынысын жасау мүмкін болмады. Кейінірек қайталаңыз." if language == "kk"
            else "Не удалось получить предложение AI. Попробуйте позже."
        )
        return redirect(f"/saved/?language={language}")

    request.session[_change_session_key(token)] = {
        "recipe": suggestion["recipe"],
        "changes": suggestion["changes"],
        "instruction": instruction,
    }
    return redirect(f"/saved/?language={language}")


@require_POST
def accept_recipe_change(request, token):
    item = get_object_or_404(SavedRecipe, token=token)
    key = _change_session_key(token)
    suggestion = request.session.get(key)
    if not isinstance(suggestion, dict) or not isinstance(suggestion.get("recipe"), str):
        return redirect(f"/saved/?language={get_language(request.POST.get('language', item.language))}")

    # Keep exactly one previous accepted version; a new accept replaces the undo point.
    item.previous_recipe = item.recipe
    item.recipe = suggestion["recipe"]
    item.save(update_fields=["previous_recipe", "recipe"])
    request.session.pop(key, None)
    return redirect(f"/saved/?language={get_language(request.POST.get('language', item.language))}")


@require_POST
def reject_recipe_change(request, token):
    item = get_object_or_404(SavedRecipe, token=token)
    request.session.pop(_change_session_key(token), None)
    return redirect(f"/saved/?language={get_language(request.POST.get('language', item.language))}")


@require_POST
def undo_recipe_change(request, token):
    item = get_object_or_404(SavedRecipe, token=token)
    if item.previous_recipe is not None:
        item.recipe = item.previous_recipe
        item.previous_recipe = None
        item.save(update_fields=["recipe", "previous_recipe"])
    return redirect(f"/saved/?language={get_language(request.POST.get('language', item.language))}")
