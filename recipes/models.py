
import uuid
from django.db import models

class SavedRecipe(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    products = models.CharField(max_length=500)
    recipe = models.TextField()
    # One-level undo: stores the recipe immediately before the latest accepted change.
    previous_recipe = models.TextField(blank=True, null=True)
    language = models.CharField(max_length=2, default="kk")
    minutes = models.PositiveSmallIntegerField(default=30)
    vegetarian = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
