from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("reportes", views.ReporteViewSet, basename="reporte")
router.register("me/busquedas", views.BusquedaRecienteViewSet, basename="busqueda")

urlpatterns = [
    path("auth/registro/", views.RegistroView.as_view(), name="registro"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("me/estadisticas/", views.EstadisticasView.as_view(), name="estadisticas"),
    path("mapas/manifest/", views.ManifestView.as_view(), name="manifest"),
    path("", include(router.urls)),
]
