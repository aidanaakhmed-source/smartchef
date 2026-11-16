import json
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from dotenv import dotenv_values

from .catalog import CATEGORIES, PRODUCTS, build_products
from .models import SavedRecipe


LANGUAGES = ("kk", "ru")
DEFAULT_LANGUAGE = "kk"
MINUTES_CHOICES = ("15", "30", "60")
DEFAULT_MINUTES = "30"
CHANGE_REQUEST_MIN_LENGTH = 3
CHANGE_REQUEST_MAX_LENGTH = 300
PENDING_EXPIRY_SECONDS = 600


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
    language = get_language(request.GET.get("language", DEFAULT_LANGUAGE))
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

    language = get_language(request.POST.get("language", DEFAULT_LANGUAGE))
    products = request.POST.get("products", "")
    minutes = request.POST.get("minutes", DEFAULT_MINUTES)
    vegetarian = request.POST.get("vegetarian") == "1"
    action = request.POST.get("action")
    raw_ids = request.POST.getlist("selected_products")

    selected_products = valid_selected_ids(raw_ids)

    context.update({
        "language": language,
        "products": products,
        "minutes": (minutes if minutes in MINUTES_CHOICES else DEFAULT_MINUTES),
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

    try:
        selected_products, combined = build_products(raw_ids, products, language)
    except ValueError as exc:
        context["error"] = str(exc)
        return render(request, "recipes/index.html", context)

    context["selected_products"] = selected_products

    if minutes not in MINUTES_CHOICES:
        context["error"] = messages["minutes_invalid"]
        return render(request, "recipes/index.html", context)

    config = dotenv_values(settings.BASE_DIR / ".env")
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    model = (config.get("GEMINI_MODEL") or "").strip() or "gemini-3.8-flash"

    if not api_key or api_key == "PASTE_YOUR_KEY_HERE":
        context["error"] = messages["key_missing"]
        return render(request, "recipes/index.html", context)

    prompt = build_prompt(combined, minutes, vegetarian, language)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        interaction = client.interactions.create(model=model, input=prompt)
        recipe = interaction.output_text or ""
    except Exception as exc:
        error_type = type(exc).__name__
        print("=" * 60)
        print("GEMINI ERROR:", error_type, str(exc))
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


def _get_gemini_settings():
    config = dotenv_values(settings.BASE_DIR / ".env")
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    model = (config.get("GEMINI_MODEL") or "").strip() or "gemini-3.8-flash"
    return api_key, model


def strict_json_parse(raw_text):
    """Verify the AI response is strictly a JSON object with exactly title, ingredients, steps."""
    text = str(raw_text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    def dict_no_dup(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError("Duplicate key found")
            d[k] = v
        return d

    try:
        data = json.loads(text.strip(), object_pairs_hook=dict_no_dup)
    except Exception:
        raise ValueError("Invalid JSON format")

    if not isinstance(data, dict):
        raise ValueError("Not a JSON object")

    if set(data.keys()) != {"title", "ingredients", "steps"}:
        raise ValueError("Invalid or extra keys")

    title = data["title"]
    ingredients = data["ingredients"]
    steps = data["steps"]

    if not isinstance(title, str) or not (1 <= len(title) <= 150):
        raise ValueError("Invalid title")
    if not isinstance(ingredients, list) or not (1 <= len(ingredients) <= 30) or not all(isinstance(i, str) and len(i) <= 150 for i in ingredients):
        raise ValueError("Invalid ingredients")
    if not isinstance(steps, list) or not (1 <= len(steps) <= 20) or not all(isinstance(s, str) and len(s) <= 1000 for s in steps):
        raise ValueError("Invalid steps")

    return data


def format_recipe_text(candidate, language):
    """Format the validated JSON back into plain text for the DB."""
    if language == "kk":
        ing_label = "Ингредиенттер:"
        step_label = "Дайындау қадамдары:"
    else:
        ing_label = "Ингредиенты:"
        step_label = "Шаги приготовления:"

    text = f"{candidate['title']}\n\n{ing_label}\n"
    text += "\n".join(f"- {i}" for i in candidate["ingredients"])
    text += f"\n\n{step_label}\n"
    text += "\n".join(f"{i}. {s}" for i, s in enumerate(candidate["steps"], 1))
    return text


def saved_recipes(request):
    language = get_language(request.GET.get("language", DEFAULT_LANGUAGE))

    items = list(SavedRecipe.objects.all())
    
    pending = request.session.get("smartchef_pending_change")
    if pending and time.time() > pending.get("expires_at", 0):
        request.session.pop("smartchef_pending_change", None)
        pending = None
        request.session["smartchef_change_error"] = (
            "Ұсыныстың уақыты бітті. Қайта сұраныс жіберіңіз." if language == "kk"
            else "Время предложения истекло. Отправьте запрос снова."
        )

    recipe_cards = []
    for item in items:
        suggestion = None
        if pending and pending["recipe_id"] == item.id:
            suggestion = pending["candidate"]
        recipe_cards.append({"item": item, "suggestion": suggestion})

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


@require_POST
def request_recipe_change(request, token):
    item = get_object_or_404(SavedRecipe, token=token)
    language = get_language(request.POST.get("language", item.language))
    instruction = request.POST.get("instruction", "").strip()

    if not instruction or not (CHANGE_REQUEST_MIN_LENGTH <= len(instruction) <= CHANGE_REQUEST_MAX_LENGTH):
        request.session["smartchef_change_error"] = (
            f"Өзгерту сұрауы {CHANGE_REQUEST_MIN_LENGTH}–{CHANGE_REQUEST_MAX_LENGTH} таңба болуы керек." if language == "kk"
            else f"Запрос должен содержать от {CHANGE_REQUEST_MIN_LENGTH} до {CHANGE_REQUEST_MAX_LENGTH} символов."
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
        "Return valid JSON only, with exactly these keys: "
        '{"title": "string", "ingredients": ["string"], "steps": ["string"]}. '
        "Do not wrap JSON in markdown. Do not add extra keys. The entire recipe must be in "
        f"{LANGUAGE_NAMES[language]}.\n\n"
        f"SAVED RECIPE:\n{item.recipe}\n\nUSER CHANGE REQUEST:\n{instruction}"
    )

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        interaction = client.interactions.create(model=model, input=prompt)
        raw_output = interaction.output_text or ""
        
        if not raw_output.strip():
            raise ValueError("Empty AI response")
            
        candidate = strict_json_parse(raw_output)
    except ValueError as exc:
        request.session["smartchef_change_error"] = (
            f"AI жауабы дұрыс форматта емес: {str(exc)}" if language == "kk"
            else f"Ответ AI неверного формата: {str(exc)}"
        )
        return redirect(f"/saved/?language={language}")
    except Exception as exc:
        print("SMARTCHEF CHANGE ERROR:", type(exc).__name__, str(exc))
        request.session["smartchef_change_error"] = (
            "AI ұсынысын жасау мүмкін болмады. Кейінірек қайталаңыз." if language == "kk"
            else "Не удалось получить предложение AI. Попробуйте позже."
        )
        return redirect(f"/saved/?language={language}")

    request.session["smartchef_pending_change"] = {
        "recipe_id": item.id,
        "original_recipe": item.recipe,
        "candidate": candidate,
        "token": str(uuid.uuid4()),
        "expires_at": time.time() + PENDING_EXPIRY_SECONDS,
    }
    return redirect(f"/saved/?language={language}")


@require_POST
def accept_recipe_change(request, token):
    language = get_language(request.POST.get("language", DEFAULT_LANGUAGE))
    pending = request.session.get("smartchef_pending_change")

    if not pending or pending.get("expires_at", 0) < time.time():
        request.session["smartchef_change_error"] = (
            "Қабылдау мүмкін емес: ұсыныс табылмады немесе уақыты бітті." if language == "kk"
            else "Невозможно принять: предложение не найдено или истекло время."
        )
        return redirect(f"/saved/?language={language}")

    try:
        with transaction.atomic():
            # Егер модельде owner өрісі болса, select_for_update() ішіне owner=request.user қосу керек
            item = SavedRecipe.objects.select_for_update().get(token=token)

            if item.id != pending.get("recipe_id"):
                raise ValueError("ID mismatch")

            if item.recipe != pending.get("original_recipe"):
                raise ValueError("Recipe has been modified since request (stale proposal)")

            new_recipe_text = format_recipe_text(pending["candidate"], item.language)
            item.previous_recipe = item.recipe
            item.recipe = new_recipe_text
            item.save(update_fields=["previous_recipe", "recipe"])

            request.session.pop("smartchef_pending_change", None)
            
            if hasattr(request.session, 'save'):
                try:
                    request.session.save()
                except Exception:
                    pass 

    except SavedRecipe.DoesNotExist:
        request.session["smartchef_change_error"] = (
            "Рецепт табылмады." if language == "kk"
            else "Рецепт не найден."
        )
        return redirect(f"/saved/?language={language}")
    except ValueError:
        request.session["smartchef_change_error"] = (
            "Қабылдау мүмкін емес: рецепт өзгертілген немесе ұсыныс ескірген." if language == "kk"
            else "Невозможно принять: рецепт был изменён или предложение устарело."
        )
        return redirect(f"/saved/?language={language}")
    except Exception as e:
        print("ACCEPT ERROR:", type(e).__name__, str(e))
        request.session["smartchef_change_error"] = (
            "Серверлік қате. Кейінірек қайталаңыз." if language == "kk"
            else "Ошибка сервера. Попробуйте позже."
        )
        return redirect(f"/saved/?language={language}")

    return redirect(f"/saved/?language={language}")


@require_POST
def reject_recipe_change(request, token):
    language = get_language(request.POST.get("language", DEFAULT_LANGUAGE))
    request.session.pop("smartchef_pending_change", None)
    return redirect(f"/saved/?language={language}")


@require_POST
def undo_recipe_change(request, token):
    language = get_language(request.POST.get("language", DEFAULT_LANGUAGE))
    
    try:
        with transaction.atomic():
            # Егер модельде owner өрісі болса, select_for_update() ішіне owner=request.user қосу керек
            item = get_object_or_404(SavedRecipe.objects.select_for_update(), token=token)
            
            if item.previous_recipe is not None:
                item.recipe = item.previous_recipe
                item.previous_recipe = None
                item.save(update_fields=["recipe", "previous_recipe"])
                
                request.session.pop("smartchef_pending_change", None)
                
                if hasattr(request.session, 'save'):
                    try:
                        request.session.save()
                    except Exception:
                        pass
            else:
                request.session["smartchef_change_error"] = (
                    "Болдырмау мүмкін емес: алдыңғы нұсқа жоқ." if language == "kk"
                    else "Невозможно отменить: нет предыдущей версии."
                )
    except Exception as e:
        print("UNDO ERROR:", type(e).__name__, str(e))
        request.session["smartchef_change_error"] = (
            "Серверлік қате. Кейінірек қайталаңыз." if language == "kk"
            else "Ошибка сервера. Попробуйте позже."
        )
        
    return redirect(f"/saved/?language={language}")