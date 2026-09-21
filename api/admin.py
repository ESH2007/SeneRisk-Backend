from django.contrib import admin

from .models import BusquedaReciente, Perfil, Reporte, Validacion


@admin.register(Reporte)
class ReporteAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "titulo", "lugar", "creado_en", "autor", "anonimo")
    list_filter = ("tipo", "anonimo")
    search_fields = ("titulo", "lugar", "descripcion")


admin.site.register(Perfil)
admin.site.register(Validacion)
admin.site.register(BusquedaReciente)
