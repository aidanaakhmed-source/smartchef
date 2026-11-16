import json
from django.test import TestCase
from django.urls import reverse

from .models import SavedRecipe
from .views import _parse_change_response, _change_session_key


class SavedRecipeChangeTests(TestCase):
    def setUp(self):
        self.item = SavedRecipe.objects.create(
            products="Картоп, сәбіз",
            recipe="Бастапқы рецепт",
            language="kk",
            minutes=30,
            vegetarian=True,
        )

    def test_saved_page_shows_change_form(self):
        response = self.client.get(reverse("recipes:saved_recipes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "request-change")
        self.assertContains(response, str(self.item.token))

    def test_accept_stores_one_level_undo_snapshot(self):
        session = self.client.session
        session[_change_session_key(self.item.token)] = {
            "recipe": "Жаңа рецепт", "changes": ["Қадам өзгерді"]
        }
        session.save()

        response = self.client.post(
            reverse("recipes:accept_recipe_change", args=[self.item.token]),
            {"language": "kk"},
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.recipe, "Жаңа рецепт")
        self.assertEqual(self.item.previous_recipe, "Бастапқы рецепт")

    def test_reject_does_not_change_saved_recipe(self):
        session = self.client.session
        session[_change_session_key(self.item.token)] = {
            "recipe": "Ұсынылған рецепт", "changes": []
        }
        session.save()
        self.client.post(
            reverse("recipes:reject_recipe_change", args=[self.item.token]),
            {"language": "kk"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.recipe, "Бастапқы рецепт")
        self.assertIsNone(self.item.previous_recipe)
        self.assertNotIn(_change_session_key(self.item.token), self.client.session)

    def test_undo_restores_previous_recipe_and_clears_undo_point(self):
        self.item.recipe = "Қабылданған жаңа рецепт"
        self.item.previous_recipe = "Бастапқы рецепт"
        self.item.save()
        self.client.post(
            reverse("recipes:undo_recipe_change", args=[self.item.token]),
            {"language": "kk"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.recipe, "Бастапқы рецепт")
        self.assertIsNone(self.item.previous_recipe)

    def test_second_accept_replaces_single_undo_point(self):
        self.item.recipe = "Бірінші өзгеріс"
        self.item.previous_recipe = "Ескі рецепт"
        self.item.save()
        session = self.client.session
        session[_change_session_key(self.item.token)] = {
            "recipe": "Екінші өзгеріс", "changes": []
        }
        session.save()
        self.client.post(
            reverse("recipes:accept_recipe_change", args=[self.item.token]),
            {"language": "kk"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.recipe, "Екінші өзгеріс")
        self.assertEqual(self.item.previous_recipe, "Бірінші өзгеріс")

    def test_json_response_is_validated(self):
        parsed = _parse_change_response(json.dumps({
            "recipe": "Толық рецепт", "changes": ["Өнім ауысты"]
        }, ensure_ascii=False))
        self.assertEqual(parsed["recipe"], "Толық рецепт")
        self.assertEqual(parsed["changes"], ["Өнім ауысты"])

    def test_invalid_ai_json_is_rejected(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            _parse_change_response("Бұл JSON емес")

    def test_change_request_rejects_empty_instruction_without_ai_call(self):
        response = self.client.post(
            reverse("recipes:request_recipe_change", args=[self.item.token]),
            {"language": "kk", "instruction": "   "},
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.recipe, "Бастапқы рецепт")
