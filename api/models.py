from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point


class TipoHecho(models.TextChoices):
    BLOQUEO = "bloqueo", "Bloqueo"
    PROTESTA = "protesta", "Protesta"
    INCENDIO = "incendio", "Incendio"
    AGRESION = "agresion", "Agresión"
    VANDALISMO = "vandalismo", "Vandalismo"
    DESAPARECIDA = "desaparecida", "Persona desaparecida"


# Severidad 1..5 por tipo, usada como peso base del mapa de calor.
SEVERIDAD_POR_TIPO = {
    TipoHecho.AGRESION: 5,
    TipoHecho.DESAPARECIDA: 5,
    TipoHecho.INCENDIO: 4,
    TipoHecho.BLOQUEO: 2,
    TipoHecho.PROTESTA: 2,
    TipoHecho.VANDALISMO: 3,
}


class Perfil(models.Model):
    """Preferencias del usuario (pantalla Configuración)."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    notificaciones = models.BooleanField(default=True)
    radio_km = models.FloatField(default=5)
    anonimo_por_defecto = models.BooleanField(default=True)

    def __str__(self):
        return f"Perfil de {self.usuario}"


class Reporte(models.Model):
    tipo = models.CharField(max_length=20, choices=TipoHecho.choices, db_index=True)
    titulo = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    lugar = models.CharField(max_length=160)
    lat = models.FloatField()
    lng = models.FloatField()
    # Derivado de lat/lng en save(); es lo que usan los filtros espaciales (índice GiST).
    ubicacion = models.PointField(geography=True, srid=4326)
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reportes"
    )
    anonimo = models.BooleanField(default=True)
    foto = models.ImageField(upload_to="reportes/", null=True, blank=True)
    severidad = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [models.Index(fields=["tipo", "creado_en"])]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.lugar}"

    def save(self, *args, **kwargs):
        if not self.pk and self.severidad == 3:
            self.severidad = SEVERIDAD_POR_TIPO.get(self.tipo, 3)
        self.ubicacion = Point(self.lng, self.lat, srid=4326)
        super().save(*args, **kwargs)


class Validacion(models.Model):
    """Un usuario confirma o desmiente un reporte (una sola vez por reporte)."""

    reporte = models.ForeignKey(Reporte, on_delete=models.CASCADE, related_name="validaciones")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="validaciones")
    confirma = models.BooleanField()
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["reporte", "usuario"], name="una_validacion_por_usuario")]


class BusquedaReciente(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="busquedas")
    texto = models.CharField(max_length=160)
    creado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [models.UniqueConstraint(fields=["usuario", "texto"], name="busqueda_unica_por_usuario")]
