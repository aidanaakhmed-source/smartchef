from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0002_savedrecipe_delete_recipememory"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedrecipe",
            name="previous_recipe",
            field=models.TextField(blank=True, null=True),
        ),
    ]
