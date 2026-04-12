from django.conf.urls import url, include
from django.conf.urls.static import static
from django.contrib import admin
from workshop_portal import views
from django.conf import settings


urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^$', views.index),
    url(r'^workshop/', include('workshop_app.urls')),
    url(r'^reset/', include('django.contrib.auth.urls')),
    url(r'^page/', include('cms.urls')),
    url(r'^statistics/', include('statistics_app.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
