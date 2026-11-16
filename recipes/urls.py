
from django.urls import path
from . import views

app_name = "recipes"
urlpatterns = [
    path("", views.index, name="index"),
    path("save/", views.save_recipe, name="save_recipe"),
    path("saved/", views.saved_recipes, name="saved_recipes"),
    path("saved/<uuid:token>/request-change/", views.request_recipe_change, name="request_recipe_change"),
    path("saved/<uuid:token>/accept/", views.accept_recipe_change, name="accept_recipe_change"),
    path("saved/<uuid:token>/reject/", views.reject_recipe_change, name="reject_recipe_change"),
    path("saved/<uuid:token>/undo/", views.undo_recipe_change, name="undo_recipe_change"),
]
