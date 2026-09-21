import math

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import BusquedaReciente, Perfil, Reporte, TipoHecho

User = get_user_model()


def distancia_km(lat1, lng1, lat2, lng2):
    """Haversine, suficiente para "a 1,2 km"."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---- cuenta ---------------------------------------------------------------------------


class UsuarioSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source="first_name", max_length=150)
    correo = serializers.EmailField(source="email")

    class Meta:
        model = User
        fields = ["id", "nombre", "correo"]

    def validate_correo(self, value):
        value = value.lower().strip()
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return value

    def update(self, instance, validated_data):
        if "email" in validated_data:
            instance.username = validated_data["email"]
        return super().update(instance, validated_data)


class RegistroSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=150)
    correo = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_correo(self, value):
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["correo"],
            email=validated_data["correo"],
            password=validated_data["password"],
            first_name=validated_data["nombre"].strip(),
        )
        Perfil.objects.create(usuario=user)
        return user


class LoginSerializer(serializers.Serializer):
    correo = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["correo"].lower().strip(), password=attrs["password"])
        if not user:
            raise serializers.ValidationError("Correo o contraseña incorrectos.")
        attrs["user"] = user
        return attrs


class ConfiguracionSerializer(serializers.ModelSerializer):
    radioKm = serializers.FloatField(source="radio_km", min_value=1, max_value=10)
    anonimoPorDefecto = serializers.BooleanField(source="anonimo_por_defecto")

    class Meta:
        model = Perfil
        fields = ["notificaciones", "radioKm", "anonimoPorDefecto"]


class EstadisticasSerializer(serializers.Serializer):
    reportes = serializers.IntegerField()
    confirmaciones = serializers.IntegerField()
    fiabilidad = serializers.FloatField(help_text="0..1: confirmaciones / (confirmaciones + desmentidos) de mis reportes")


# ---- reportes -------------------------------------------------------------------------


class ReporteSerializer(serializers.ModelSerializer):
    """Misma forma que `Reporte` en el front. Confirmaciones y desmentidos vienen anotados."""

    creadoEn = serializers.DateTimeField(source="creado_en", read_only=True)
    confirmaciones = serializers.IntegerField(read_only=True)
    desmentidos = serializers.IntegerField(read_only=True)
    distanciaKm = serializers.SerializerMethodField()
    miValidacion = serializers.SerializerMethodField(help_text="true/false si ya validé, null si no")
    foto = serializers.ImageField(required=False, allow_null=True)
    # allow_null: si no viene (también en multipart) se usa `anonimoPorDefecto` del perfil.
    anonimo = serializers.BooleanField(required=False, allow_null=True)

    class Meta:
        model = Reporte
        fields = [
            "id", "tipo", "titulo", "descripcion", "lugar", "lat", "lng", "creadoEn",
            "anonimo", "foto", "severidad", "confirmaciones", "desmentidos", "distanciaKm", "miValidacion",
        ]
        read_only_fields = ["severidad"]

    def validate_lat(self, v):
        if not -90 <= v <= 90:
            raise serializers.ValidationError("Latitud fuera de rango.")
        return v

    def validate_lng(self, v):
        if not -180 <= v <= 180:
            raise serializers.ValidationError("Longitud fuera de rango.")
        return v

    def get_distanciaKm(self, obj):
        origen = self.context.get("origen")
        if not origen:
            return None
        return round(distancia_km(origen[0], origen[1], obj.lat, obj.lng), 2)

    def get_miValidacion(self, obj):
        return getattr(obj, "mi_validacion", None)


class ValidacionSerializer(serializers.Serializer):
    confirma = serializers.BooleanField()


class CalorSerializer(serializers.ModelSerializer):
    """Punto para el mapa de calor: misma forma que `RiskReport` en el front."""

    createdAt = serializers.DateTimeField(source="creado_en")
    severity = serializers.IntegerField(source="severidad")
    validations = serializers.IntegerField(source="confirmaciones")
    category = serializers.CharField(source="tipo")

    class Meta:
        model = Reporte
        fields = ["id", "lat", "lng", "createdAt", "severity", "validations", "category"]


class CalorQuerySerializer(serializers.Serializer):
    """Parámetros de /reportes/calor/."""

    bbox = serializers.CharField(help_text="minLng,minLat,maxLng,maxLat")
    desde = serializers.DateTimeField(required=False)
    hasta = serializers.DateTimeField(required=False)
    categorias = serializers.CharField(required=False, help_text="coma-separadas")
    celda = serializers.FloatField(required=False, min_value=0.0005, max_value=1, help_text="tamaño de celda en grados; agrega en servidor")

    def validate_bbox(self, value):
        try:
            b = [float(x) for x in value.split(",")]
        except ValueError:
            raise serializers.ValidationError("bbox debe ser minLng,minLat,maxLng,maxLat")
        if len(b) != 4 or b[0] >= b[2] or b[1] >= b[3]:
            raise serializers.ValidationError("bbox inválido")
        return b

    def validate_categorias(self, value):
        cats = {c.strip() for c in value.split(",") if c.strip()}
        malas = cats - set(TipoHecho.values)
        if malas:
            raise serializers.ValidationError(f"categorías desconocidas: {', '.join(sorted(malas))}")
        return cats


class BusquedaRecienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusquedaReciente
        fields = ["id", "texto", "creado_en"]
        read_only_fields = ["creado_en"]
