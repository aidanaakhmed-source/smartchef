import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.urls import reverse
from .models import SavedRecipe

class RecipeChangeTests(TestCase):
    def setUp(self):
        self.recipe = SavedRecipe.objects.create(
            products="Картоп",
            recipe="Бастапқы рецепт",
            language="kk",
            minutes=30,
            vegetarian=False
        )
        # Сессияны сұраныс арқылы инициализациялау
        self.client.get(reverse('recipes:index'))

    @patch('google.genai.Client')
    def test_propose_accept_and_one_level_undo(self, mock_client_class):
        # 1. AI-ды Mock-таймыз
        mock_client = MagicMock()
        mock_interaction = MagicMock()
        mock_interaction.output_text = json.dumps({
            "title": "Жаңа рецепт",
            "ingredients": ["Картоп", "Су"],
            "steps": ["Пісіру"]
        }, ensure_ascii=False)
        mock_client.interactions.create.return_value = mock_interaction
        mock_client_class.return_value = mock_client

        # 2. Propose (Сұраныс жіберу)
        url = reverse('recipes:request_recipe_change', args=[self.recipe.token])
        response = self.client.post(url, {'instruction': 'Жаңа нұсқа', 'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        session = self.client.session
        pending = session.get('smartchef_pending_change')
        self.assertIsNotNone(pending)
        self.assertEqual(pending['recipe_id'], self.recipe.id)

        # 3. Accept (Қабылдау)
        url_accept = reverse('recipes:accept_recipe_change', args=[self.recipe.token])
        response = self.client.post(url_accept, {'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        self.recipe.refresh_from_db()
        self.assertIn('Жаңа рецепт', self.recipe.recipe)
        self.assertEqual(self.recipe.previous_recipe, 'Бастапқы рецепт')

        # 4. Undo (Болдырмау - бірінші рет)
        url_undo = reverse('recipes:undo_recipe_change', args=[self.recipe.token])
        response = self.client.post(url_undo, {'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.recipe, 'Бастапқы рецепт')
        self.assertIsNone(self.recipe.previous_recipe)

        # 5. Undo (Екінші рет - орындалмауы керек, өйткені snapshot жойылды)
        response = self.client.post(url_undo, {'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.recipe, 'Бастапқы рецепт')
        self.assertIsNone(self.recipe.previous_recipe)

    @patch('google.genai.Client')
    def test_reject_and_error_handling(self, mock_client_class):
        # 1. Қате жағдайын тексеру (Error)
        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        url = reverse('recipes:request_recipe_change', args=[self.recipe.token])
        response = self.client.post(url, {'instruction': 'Қате', 'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        session = self.client.session
        self.assertEqual(session.get('smartchef_change_error'), "AI ұсынысын жасау мүмкін болмады. Кейінірек қайталаңыз.")
        self.assertIsNone(session.get('smartchef_pending_change'))
        
        # Тазалау (әрі қарайғы тестке кедергі жасамауы үшін)
        session.pop('smartchef_change_error', None)
        session.save()

        # 2. Reject (Бас тарту)
        mock_client.interactions.create.side_effect = None
        mock_interaction = MagicMock()
        mock_interaction.output_text = json.dumps({
            "title": "Тест", "ingredients": ["A"], "steps": ["B"]
        })
        mock_client.interactions.create.return_value = mock_interaction
        
        self.client.post(url, {'instruction': 'Жарамды сұрау', 'language': 'kk'})
        session = self.client.session
        self.assertIsNotNone(session.get('smartchef_pending_change'))

        url_reject = reverse('recipes:reject_recipe_change', args=[self.recipe.token])
        response = self.client.post(url_reject, {'language': 'kk'})
        self.assertRedirects(response, '/saved/?language=kk', fetch_redirect_response=False)
        
        session = self.client.session
        self.assertIsNone(session.get('smartchef_pending_change'))
        
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.recipe, 'Бастапқы рецепт')