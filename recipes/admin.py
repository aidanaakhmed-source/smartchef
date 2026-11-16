from django.contrib import admin
from .models import SavedRecipe


@admin.register(SavedRecipe)
class SavedRecipeAdmin(admin.ModelAdmin):
    list_display = (
        "products",
        "language",
        "minutes",
        "vegetarian",
        "created_at",
    )
    readonly_fields = ("token", "created_at")
    search_fields = ("products", "recipe")