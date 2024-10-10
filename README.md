# gaia (geOrchestra Automated Integrity Analysis) - a geOrchestra dashboard

this project aims at providing a user-centric dashboard for [geOrchestra](https://georchestra.org):
- for admins, showing inconsistencies/errors in the datasets/maps, reusing what
  was done in [sdi-consistency-check](https://github.com/georchestra/sdi-consistence-check/)
- for users, direct links to:
  - what they can access
  - what they can do (depending on their rights/roles)
  - list their md/data
  - list their org md

one of the goals is to provide an api returning JSON so that it can be reused in
other components/webpages (such as the [ids
homepage](https://github.com/georchestra/htdocs/))

it is a work in progress, being developed when spare time is available. for now
developped in my own github account, but if enough features are developed and
interest is shown, it'll move to the
[geOrchestra](https://github.com/georchestra/) organization.

## dependencies

written using the versions of python/flask/celery provided by debian 12, it
should only require 'recent' versions of those:

```
apt install python3-flask-bootstrap python3-flask python3-celery python3-sqlalchemy python3-psycopg2 python3-owslib python3-jsonpickle python3-redis
```

those dependencies are used for:
- the web interface : [flask 2.2](https://flask.palletsprojects.com/en/2.2.x/) and [flask-bootstrap](https://bootstrap-flask.readthedocs.io/en/stable/)
- the job queue to run the checks in background tasks : [celery 5.2](https://docs.celeryq.dev/en/v5.2.6/)
- interaction with the sql database: [sqlalchemy 1.4](https://docs.sqlalchemy.org/en/14/) and [psycopg2](https://www.psycopg.org/)
- interaction with the WMS/WFS/WMTS/CSW services: [owslib](https://owslib.readthedocs.io/en/latest/)
- serializing the capabilities of the services: [jsonpickle](https://jsonpickle.github.io/)
- and finally caching them: [redis](https://redis.io/docs/latest/develop/connect/clients/python/redis-py/)

with this caching, we avoid hammering the remote OGC services continually asking
them for a capabilities document that might be expensive to produce sometimes.

## integration

the web service should be added behind geOrchestra's security-proxy/gateway, so
that it knows the connected user and can display user-tailored information.

add this line to `/etc/georchestra/security-proxy/target-mappings.properties`:
```
gaia=http://<hostname>:<port>/gaia/
```

and visit https://<idsurl>/gaia/, which should list for now:
- your metadatas
- the maps & contexts you can access

if your datadir isn't in `/etc/georchestra`, point the `georchestradatadir`
environment variable to the path where your datadir is located.

## pages

here's a quick list of pages/routes implemented so far, the goal is to have as
much interlinking as possible.

the logic behind each url/route is that if you know what you want to access, be
it a given OGC layer by its short name, a metadata by its uuid, or a mapstore
map by its numeric id, you should be able to directly access it by typing the
url in your browser.

### `/`
lists:
- metadatas belonging to the connected user
- maps and contexts he is allowed to visit

### `/admin/`
- lists all maps and contexts current problems
- allows to manually trigger a check for the integrity of all maps/contexts

### `/map/<mapid>`
- displays map details & current problems
- links to the OGC layers used by the map

### `/ctx/<mapid>`
- displays ctx map details & current problems
- links to the OGC layers used by the ctx map

### `/ows/<{wms,wfs,wmts}>/<service url>/`
- displays contents of a given OGC service
- shows the list of all problems for all layers in the service
- `service url` is an url with slashes replaced by `~`, eg `~geoserver~wms` for the default WMS geoserver, `~geoserver~workspace~ows` for a workspace
- full urls such as `https:~~wmts.craig.fr~pci~service` can be used, if the `https:~~fqdn` part is omitted the georchestra FQDN is assumed

### `/ows/<{wms,wfs,wmts}>/<service url>/<layername>`
- displays the details about a given layer in a given OGC service
- links to the mapstore maps & contexts that use this layer
- links to the metadata page
- allow to preview the layer in geoserver, or open it in mapstore
- links to the geoserver layer edit page
- shows the list of all problems for all layers in the service

### `/csw/<portal>`
- displays the lists of metadatas in a given CSW portal, eg `/csw/srv` for all
  metadatas, and if you've created an `opendata` portal then `/csw/opendata`
  lists the metadatas in this CSW endpoint.

### `/csw/<portal>/<uuid>`
- displays the details about a given metadata in a given CSW portal
- allows to view the metadata in datahub/geonetwork
- links to the editor view in geonetwork
- links to the OGC:W{M,F}S layers listed in the metadata

## service

needs two services running (TODO)
- the flask webapp, accessed at `https://<idsurl>/gaia/`
- the celery worker, for long-running checks

for now during development those are started by [`run.sh`](run.sh), proper
integration via gunicorn/systemd is the goal

## configuration

for now a redis instance is used for celery's broker/result backend storage, to
configure in [`config.py`](config.py.example) - celery can use rabbitmq for the
broker, and in the end the geOrchestra PostgreSQL database will be used to
store task results.

it tries as much as possible to autoconfigure itself by reading configuration
files from [geOrchestra's datadir](https://github.com/georchestra/datadir)
