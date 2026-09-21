import json
from pathlib import Path

from django.conf import settings
from django.contrib.gis.db.models import GeometryField, PointField
from django.contrib.gis.db.models.functions import GeoFunc
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.db import connection
from django.db.models import Count, F, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Cast
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BusquedaReciente, Perfil, Reporte, Validacion
from .serializers import (
    BusquedaRecienteSerializer,
    CalorQuerySerializer,
    CalorSerializer,
    ConfiguracionSerializer,
    EstadisticasSerializer,
    LoginSerializer,
    RegistroSerializer,
    ReporteSerializer,
    UsuarioSerializer,
    ValidacionSerializer,
)


def _respuesta_sesion(user):
    token, _ = Token.objects.get_or_create(user=user)
    return {"token": token.key, "usuario": UsuarioSerializer(user).data}


# ---- cuenta ---------------------------------------------------------------------------


class RegistroView(GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegistroSerializer

    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(_respuesta_sesion(s.save()), status=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(_respuesta_sesion(s.validated_data["user"]))


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(RetrieveUpdateAPIView):
    serializer_class = UsuarioSerializer

    def get_object(self):
        return self.request.user


class ConfiguracionView(RetrieveUpdateAPIView):
    serializer_class = ConfiguracionSerializer

    def get_object(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        return perfil


class EstadisticasView(APIView):
    """Tarjetas del perfil: reportes propios, confirmaciones recibidas y fiabilidad."""

    def get(self, request):
        agg = Validacion.objects.filter(reporte__autor=request.user).aggregate(
            confirmaciones=Count("id", filter=Q(confirma=True)),
            desmentidos=Count("id", filter=Q(confirma=False)),
        )
        total = agg["confirmaciones"] + agg["desmentidos"]
        data = {
            "reportes": Reporte.objects.filter(autor=request.user).count(),
            "confirmaciones": agg["confirmaciones"],
            "fiabilidad": agg["confirmaciones"] / total if total else 0.0,
        }
        return Response(EstadisticasSerializer(data).data)


# ---- reportes -------------------------------------------------------------------------


def _con_conteos(qs, user=None):
    qs = qs.annotate(
        confirmaciones=Count("validaciones", filter=Q(validaciones__confirma=True)),
        desmentidos=Count("validaciones", filter=Q(validaciones__confirma=False)),
    )
    if user is not None and user.is_authenticated:
        mia = Validacion.objects.filter(reporte=OuterRef("pk"), usuario=user).values("confirma")[:1]
        qs = qs.annotate(mi_validacion=Subquery(mia))
    return qs


def _bbox(qs, bbox):
    return qs.filter(ubicacion__intersects=Polygon.from_bbox(bbox))


class SnapToGrid(GeoFunc):
    """Redondea cada punto a una rejilla de `size` grados (agregación del calor a zooms bajos)."""

    function = "ST_SnapToGrid"
    output_field = PointField(srid=4326)

    def as_sqlite(self, compiler, connection, **extra):
        return super().as_sql(compiler, connection, function="SnapToGrid", **extra)


def _a_geometria(campo):
    """`geography` → `geometry` (PostGIS lo exige para SnapToGrid); SpatiaLite no tiene geography."""
    return Cast(campo, GeometryField(srid=4326)) if connection.ops.postgis else campo


class ReporteViewSet(
    mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """
    Lista pública (mapa y alertas), creación autenticada.

    Filtros de lista: `tipo`, `bbox=minLng,minLat,maxLng,maxLat`, `desde`, `hasta` (ISO 8601),
    `lat`/`lng` (para `distanciaKm`) y `radio_km` (solo reportes a esa distancia; requiere lat/lng).
    """

    serializer_class = ReporteSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = _con_conteos(Reporte.objects.select_related("autor"), self.request.user)
        p = self.request.query_params
        if tipo := p.get("tipo"):
            qs = qs.filter(tipo=tipo)
        if bbox := p.get("bbox"):
            s = CalorQuerySerializer(data={"bbox": bbox})
            s.is_valid(raise_exception=True)
            qs = _bbox(qs, s.validated_data["bbox"])
        if desde := p.get("desde"):
            qs = qs.filter(creado_en__gte=desde)
        if hasta := p.get("hasta"):
            qs = qs.filter(creado_en__lte=hasta)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        p = self.request.query_params
        try:
            ctx["origen"] = (float(p["lat"]), float(p["lng"]))
        except (KeyError, ValueError):
            pass
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        origen = self.get_serializer_context().get("origen")
        radio = request.query_params.get("radio_km")
        if origen and radio:
            r = float(radio)
            centro = Point(origen[1], origen[0], srid=4326)
            if connection.ops.postgis:
                qs = qs.filter(ubicacion__dwithin=(centro, D(km=r)))  # ST_DWithin sobre geography, índice GiST
            else:
                # SpatiaLite no mide distancias geodésicas: bbox aproximado + Haversine en Python.
                from .serializers import distancia_km

                g = r / 111.0
                qs = _bbox(qs, [origen[1] - g, origen[0] - g, origen[1] + g, origen[0] + g])
                qs = [o for o in qs if distancia_km(origen[0], origen[1], o.lat, o.lng) <= r]
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def perform_create(self, serializer):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        anonimo = serializer.validated_data.get("anonimo")
        serializer.save(autor=self.request.user, anonimo=perfil.anonimo_por_defecto if anonimo is None else anonimo)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        self.perform_create(s)
        # Se relee con los conteos anotados para devolver exactamente lo que devuelve la lista.
        obj = _con_conteos(Reporte.objects.all(), request.user).get(pk=s.instance.pk)
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    def _validar(self, request, pk, confirma):
        reporte = Reporte.objects.get(pk=pk)
        if reporte.autor_id == request.user.id:
            return Response({"detail": "No puedes validar tu propio reporte."}, status=status.HTTP_400_BAD_REQUEST)
        Validacion.objects.update_or_create(reporte=reporte, usuario=request.user, defaults={"confirma": confirma})
        obj = _con_conteos(Reporte.objects.all(), request.user).get(pk=pk)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def confirmar(self, request, pk=None):
        return self._validar(request, pk, True)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def desmentir(self, request, pk=None):
        return self._validar(request, pk, False)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated], url_path="validar")
    def validar(self, request, pk=None):
        s = ValidacionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._validar(request, pk, s.validated_data["confirma"])

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny], pagination_class=None)
    def calor(self, request):
        """
        Puntos para el mapa de calor dentro del bbox y rango de fechas (forma de `RiskReport`).

        Con `celda=<grados>` (zooms bajos) devuelve celdas agregadas en la base de datos:
        un punto por celda con `severity` = suma, `validations` = suma, `createdAt` = más reciente,
        `category` = "agregado" y `count`.
        """
        q = CalorQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        d = q.validated_data
        qs = _bbox(Reporte.objects.all(), d["bbox"])
        qs = qs.filter(creado_en__gte=d.get("desde") or timezone.now() - timezone.timedelta(days=180))
        if d.get("hasta"):
            qs = qs.filter(creado_en__lte=d["hasta"])
        if d.get("categorias"):
            qs = qs.filter(tipo__in=d["categorias"])

        if celda := d.get("celda"):
            snap = SnapToGrid(_a_geometria(F("ubicacion")), celda)
            celdas = qs.annotate(celda=snap).values("celda").annotate(
                count=Count("id"), severity=Sum("severidad"), createdAt=Max("creado_en")
            )
            validaciones = dict(
                Validacion.objects.filter(confirma=True, reporte__in=qs)
                .annotate(celda=SnapToGrid(_a_geometria(F("reporte__ubicacion")), celda))
                .values_list("celda")
                .annotate(n=Count("id"))
            )
            return Response([
                {
                    "id": f"c{i}",
                    "lat": c["celda"].y,
                    "lng": c["celda"].x,
                    "createdAt": c["createdAt"],
                    "severity": c["severity"],
                    "validations": validaciones.get(c["celda"], 0),
                    "category": "agregado",
                    "count": c["count"],
                }
                for i, c in enumerate(celdas)
            ])

        qs = qs.annotate(confirmaciones=Count("validaciones", filter=Q(validaciones__confirma=True)))
        # ponytail: máximo 10 000 puntos por respuesta; el front pide `celda` cuando el bbox es grande.
        return Response(CalorSerializer(qs.only("id", "lat", "lng", "creado_en", "severidad", "tipo")[:10000], many=True).data)


# ---- búsquedas recientes --------------------------------------------------------------


class BusquedaRecienteViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = BusquedaRecienteSerializer
    pagination_class = None

    def get_queryset(self):
        return BusquedaReciente.objects.filter(usuario=self.request.user)

    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset()[:20], many=True).data)

    def perform_create(self, serializer):
        # Repetir una búsqueda la sube al principio en vez de duplicarla.
        obj, _ = BusquedaReciente.objects.update_or_create(
            usuario=self.request.user, texto=serializer.validated_data["texto"]
        )
        serializer.instance = obj

    @action(detail=False, methods=["delete"])
    def limpiar(self, request):
        BusquedaReciente.objects.filter(usuario=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- mapas ----------------------------------------------------------------------------


class ManifestView(APIView):
    """`manifest.json` de los PMTiles (temporal, hasta que viva en el bucket)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        path = Path(settings.MAPS_MANIFEST_PATH)
        if not path.exists():
            return Response({"detail": "manifest no generado"}, status=status.HTTP_404_NOT_FOUND)
        return Response(json.loads(path.read_text()))
