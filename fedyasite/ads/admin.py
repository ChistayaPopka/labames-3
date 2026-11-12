from django.contrib import admin

from .models import Ad, Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'price', 'city', 'author', 'is_active', 'created_at')
    list_filter = ('is_active', 'category', 'condition', 'city')
    search_fields = ('title', 'description')
    list_editable = ('is_active',)
    raw_id_fields = ('author',)
    exclude = ('favorited_by',)
    date_hierarchy = 'created_at'
