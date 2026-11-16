# Generated for SmartChef memory feature.
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="RecipeMemory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("products", models.TextField()),
                ("minutes", models.CharField(default="30", max_length=3)),
                ("vegetarian", models.BooleanField(default=False)),
                ("language", models.CharField(default="kk", max_length=2)),
                ("recipe", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
