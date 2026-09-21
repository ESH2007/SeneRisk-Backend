import django.contrib.gis.db.models.fields
from django.contrib.gis.geos import Point
from django.db import migrations


def rellenar(apps, schema_editor):
    Reporte = apps.get_model("api", "Reporte")
    for r in Reporte.objects.all():
        r.ubicacion = Point(r.lng, r.lat, srid=4326)
        r.save(update_fields=["ubicacion"])


class Migration(migrations.Migration):
    dependencies = [("api", "0001_initial")]

    operations = [
        migrations.RemoveIndex(model_name="reporte", name="api_reporte_lat_0a626e_idx"),
        # Default solo para rellenar filas existentes (SpatiaLite no permite ALTER de columnas geométricas).
        migrations.AddField(
            model_name="reporte",
            name="ubicacion",
            field=django.contrib.gis.db.models.fields.PointField(geography=True, srid=4326, default=Point(0, 0, srid=4326)),
            preserve_default=False,
        ),
        migrations.RunPython(rellenar, migrations.RunPython.noop),
    ]
