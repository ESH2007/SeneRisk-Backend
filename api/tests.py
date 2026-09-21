from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Reporte, Validacion

User = get_user_model()


def _png():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return SimpleUploadedFile("f.png", buf.getvalue(), content_type="image/png")


class CuentaTests(APITestCase):
    def test_registro_login_me_configuracion(self):
        r = self.client.post("/api/auth/registro/", {"nombre": "Juan Pérez", "correo": "Juan@Email.com", "password": "clave-segura-123"})
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data["usuario"], {"id": r.data["usuario"]["id"], "nombre": "Juan Pérez", "correo": "juan@email.com"})
        token = r.data["token"]

        # correo duplicado
        r2 = self.client.post("/api/auth/registro/", {"nombre": "Otro", "correo": "juan@email.com", "password": "clave-segura-123"})
        self.assertEqual(r2.status_code, 400)

        r = self.client.post("/api/auth/login/", {"correo": "juan@email.com", "password": "mala"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/auth/login/", {"correo": "juan@email.com", "password": "clave-segura-123"})
        self.assertEqual(r.data["token"], token)

        self.assertEqual(self.client.get("/api/me/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        r = self.client.patch("/api/me/", {"nombre": "Juan P."})
        self.assertEqual(r.data["nombre"], "Juan P.")

        r = self.client.get("/api/me/configuracion/")
        self.assertEqual(r.data, {"notificaciones": True, "radioKm": 5.0, "anonimoPorDefecto": True})
        r = self.client.put("/api/me/configuracion/", {"notificaciones": False, "radioKm": 8, "anonimoPorDefecto": False})
        self.assertEqual(r.data["radioKm"], 8.0)
        self.assertEqual(self.client.put("/api/me/configuracion/", {"notificaciones": True, "radioKm": 50, "anonimoPorDefecto": True}).status_code, 400)

        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/me/").status_code, 401)


class ReporteTests(APITestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana@x.com", email="ana@x.com", password="x", first_name="Ana")
        self.beto = User.objects.create_user("beto@x.com", email="beto@x.com", password="x", first_name="Beto")
        self.r1 = Reporte.objects.create(tipo="agresion", titulo="Riña", lugar="Cra 15 con Calle 100", lat=4.6836, lng=-74.0480, autor=self.ana)
        self.r2 = Reporte.objects.create(tipo="bloqueo", titulo="Bloqueo", lugar="Calle 13", lat=4.6141, lng=-74.1050, autor=self.ana)
        Reporte.objects.create(tipo="incendio", titulo="Lejos", lugar="Medellín", lat=6.25, lng=-75.57, autor=self.beto)

    def _como(self, user):
        self.client.force_authenticate(user)

    def test_lista_publica_con_filtros_y_distancia(self):
        r = self.client.get("/api/reportes/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 3)
        self.assertIsNone(r.data["results"][0]["distanciaKm"])
        self.assertEqual(r.data["results"][0]["confirmaciones"], 0)

        r = self.client.get("/api/reportes/", {"tipo": "bloqueo"})
        self.assertEqual([x["titulo"] for x in r.data["results"]], ["Bloqueo"])

        r = self.client.get("/api/reportes/", {"bbox": "-74.35,4.45,-73.95,4.95"})
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(self.client.get("/api/reportes/", {"bbox": "mal"}).status_code, 400)

        r = self.client.get("/api/reportes/", {"lat": 4.676, "lng": -74.048, "radio_km": 2})
        self.assertEqual([x["titulo"] for x in r.data["results"]], ["Riña"])
        self.assertAlmostEqual(r.data["results"][0]["distanciaKm"], 0.85, delta=0.05)

    def test_crear_requiere_auth_y_usa_anonimo_por_defecto(self):
        datos = {"tipo": "protesta", "titulo": "Marcha", "descripcion": "d", "lugar": "Cl 26", "lat": 4.61, "lng": -74.07}
        self.assertEqual(self.client.post("/api/reportes/", datos).status_code, 401)
        self._como(self.beto)
        r = self.client.post("/api/reportes/", {**datos, "foto": _png()}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["anonimo"])
        self.assertEqual(r.data["severidad"], 2)
        self.assertEqual(r.data["confirmaciones"], 0)
        self.assertTrue(r.data["foto"].endswith(".png"))
        self.assertEqual(self.client.post("/api/reportes/", {**datos, "lat": 95}).status_code, 400)
        self.assertEqual(self.client.post("/api/reportes/", {**datos, "tipo": "meteorito"}).status_code, 400)

    def test_confirmar_desmentir_una_vez_por_usuario_y_no_propio(self):
        self._como(self.beto)
        r = self.client.post(f"/api/reportes/{self.r1.id}/confirmar/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["confirmaciones"], r.data["desmentidos"], r.data["miValidacion"]), (1, 0, True))
        r = self.client.post(f"/api/reportes/{self.r1.id}/desmentir/")
        self.assertEqual((r.data["confirmaciones"], r.data["desmentidos"], r.data["miValidacion"]), (0, 1, False))
        self.assertEqual(Validacion.objects.count(), 1)
        r = self.client.post(f"/api/reportes/{self.r1.id}/validar/", {"confirma": True})
        self.assertEqual(r.data["miValidacion"], True)

        self._como(self.ana)
        self.assertEqual(self.client.post(f"/api/reportes/{self.r1.id}/confirmar/").status_code, 400)
        r = self.client.get(f"/api/reportes/{self.r1.id}/")
        self.assertEqual((r.data["confirmaciones"], r.data["miValidacion"]), (1, None))

        r = self.client.get("/api/me/estadisticas/")
        self.assertEqual(r.data, {"reportes": 2, "confirmaciones": 1, "fiabilidad": 1.0})

    def test_calor(self):
        Validacion.objects.create(reporte=self.r1, usuario=self.beto, confirma=True)
        viejo = Reporte.objects.create(tipo="bloqueo", titulo="Viejo", lugar="x", lat=4.65, lng=-74.06)
        Reporte.objects.filter(pk=viejo.pk).update(creado_en=timezone.now() - timezone.timedelta(days=200))

        r = self.client.get("/api/reportes/calor/", {"bbox": "-74.35,4.45,-73.95,4.95"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual({p["id"] for p in r.data}, {self.r1.id, self.r2.id}, "excluye Medellín y >180 días")
        p = next(p for p in r.data if p["id"] == self.r1.id)
        self.assertEqual((p["severity"], p["validations"], p["category"]), (5, 1, "agresion"))
        self.assertEqual(set(p.keys()), {"id", "lat", "lng", "createdAt", "severity", "validations", "category"})

        r = self.client.get("/api/reportes/calor/", {"bbox": "-74.35,4.45,-73.95,4.95", "categorias": "bloqueo"})
        self.assertEqual([p["id"] for p in r.data], [self.r2.id])
        self.assertEqual(self.client.get("/api/reportes/calor/", {"bbox": "-74.35,4.45,-73.95,4.95", "categorias": "ovni"}).status_code, 400)
        self.assertEqual(self.client.get("/api/reportes/calor/").status_code, 400)

    def test_calor_agregado_por_celda(self):
        Validacion.objects.create(reporte=self.r1, usuario=self.beto, confirma=True)
        # r1 (4.6836,-74.048) y r2 (4.6141,-74.105) caen en celdas distintas de 0.05°; con 1° en la misma.
        r = self.client.get("/api/reportes/calor/", {"bbox": "-74.35,4.45,-73.95,4.95", "celda": 0.05})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data), 2)
        c1 = next(c for c in r.data if c["validations"] == 1)
        self.assertEqual((c1["count"], c1["severity"], c1["category"]), (1, 5, "agregado"))
        self.assertAlmostEqual(c1["lat"], 4.6836, delta=0.03)  # nodo de rejilla más cercano
        r = self.client.get("/api/reportes/calor/", {"bbox": "-74.35,4.45,-73.95,4.95", "celda": 1})
        self.assertEqual(len(r.data), 1)
        self.assertEqual((r.data[0]["count"], r.data[0]["severity"], r.data[0]["validations"]), (2, 7, 1))


class BusquedasTests(APITestCase):
    def test_crud_y_sin_duplicados(self):
        u = User.objects.create_user("u@x.com", password="x")
        self.client.force_authenticate(u)
        self.client.post("/api/me/busquedas/", {"texto": "Parque de la 93"})
        self.client.post("/api/me/busquedas/", {"texto": "Calle 100"})
        self.client.post("/api/me/busquedas/", {"texto": "Parque de la 93"})
        r = self.client.get("/api/me/busquedas/")
        self.assertEqual([b["texto"] for b in r.data], ["Parque de la 93", "Calle 100"])
        self.assertEqual(self.client.delete(f"/api/me/busquedas/{r.data[1]['id']}/").status_code, 204)
        self.assertEqual(self.client.delete("/api/me/busquedas/limpiar/").status_code, 204)
        self.assertEqual(self.client.get("/api/me/busquedas/").data, [])


class ManifestTests(APITestCase):
    def test_manifest_publico(self):
        r = self.client.get("/api/mapas/manifest/")
        self.assertIn(r.status_code, (200, 404))
        if r.status_code == 200:
            self.assertIn("regions", r.data)
