# inscricoes/templatetags/site_images.py
from django import template
from django.utils.html import format_html
from inscricoes.models import SiteImage

register = template.Library()

@register.simple_tag
def site_image(key, css_class="", alt=None):
    """
    Uso:
      {% load site_images %}
      {% site_image "dashboard" "w-full h-56 object-cover rounded" alt="Painel" %}
    """
    try:
        obj = SiteImage.objects.get(key=key, ativa=True)
    except SiteImage.DoesNotExist:
        return ""
    try:
        url = obj.imagem.url
    except Exception:
        return ""
    alt_text = alt or obj.alt_text or obj.titulo or key
    return format_html('<img src="{}" alt="{}" class="{}" loading="lazy"/>',
                       url, alt_text, css_class)
