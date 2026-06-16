from django.http import JsonResponse


def health(request):
    """Endpoint de salud para el smoke HTTP (B2.4)."""
    return JsonResponse({"ok": True})


def root(request):
    """Raíz: devuelve JSON simple para que el smoke verifique `/`."""
    return JsonResponse({"ok": True})
