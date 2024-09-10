#!/bin/env python3
# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 et

import requests

from celery import shared_task
from celery import Task
from celery.utils.log import get_task_logger
tasklogger = get_task_logger(__name__)

from task_app.checks.mapstore import msc
from task_app.dashboard import unmunge

import xml.etree.ElementTree as ET
from owslib.util import ServiceException

def find_tilematrix_center(wmts, lname):
    """
    for a given wmts layer, find the 'center' tile at the last tilematrix level
    and return a tuple with:
    - the last tilematrix level to query
    - the tilematrix name
    - the row/column index at the center of the matrix
    """
    # find first tilematrixset
    # tilematrixset is a service attribute
    tsetk = list(wmts.tilematrixsets.keys())[0]
    tset = wmts.tilematrixsets[tsetk]
    # find last tilematrix level
    tmk = list(tset.tilematrix.keys())[-1]
    lasttilematrix = tset.tilematrix[tmk]
#    print(f"first tilematrixset named {tsetk}: {tset}")
#    print(f"last tilematrix lvl named {tmk}: {lasttilematrix} (type {type(lasttilematrix)}")
#    print(f"width={lasttilematrix.matrixwidth}, height={lasttilematrix.matrixheight}")
    # tilematrixsetlink is a layer attribute
    l = wmts.contents[lname]
    tms = list(l.tilematrixsetlinks.keys())[0]
#    print(f"first tilesetmatrixlink for layer {lname} named {tms}")
    tsetl = l.tilematrixsetlinks[tms]
    #geoserver/gwc sets tilematrixsetlinks, mapproxy doesnt
    if len(tsetl.tilematrixlimits) > 0:
        tmk = list(tsetl.tilematrixlimits.keys())[-1]
        tml = tsetl.tilematrixlimits[tmk]
        r = tml.mintilerow + int((tml.maxtilerow - tml.mintilerow) / 2)
        c = tml.mintilecol + int((tml.maxtilecol - tml.mintilecol) / 2)
    else:
        r = int(int(lasttilematrix.matrixwidth) / 2)
        c = int(int(lasttilematrix.matrixheight) / 2)
    return (tms, tmk, r, c)

def reduced_bbox(bbox):
    """
    for a layer bounding box, return a very small bbox at the center of it
    used for getmap/getfeature tests to ensure it doesn't hammer the remote
    """
    xmin, ymin, xmax, ymax = bbox
    return [xmin+0.49*(xmax-xmin),
         ymin+0.49*(ymax-ymin),
         xmax-0.49*(xmax-xmin),
         ymax-0.49*(ymax-ymin)]

@shared_task()
def owslayer(stype, url, layername):
    """
    Given an ows layer check that:
    - it refers to existing metadata ids
    - a getmap/getfeature/gettile query succeeds
    :param stype: the service type (wms/wfs/wmts)
    :param url: the service url
    :param layername: the layer name in the service object
    :return: the list of errors
    """
    tasklogger.info(f"checking layer {layername} in {stype} {url}")
    ret = dict()
    ret['problems'] = list()
    url = unmunge(url)
    service = msc.owscache.get(stype, url)
    localmduuids = set()
    localdomain = "https://" + msc.conf.get("domainName")
    # XXX for wfs, no metadataUrls are found by owslib, be it with 1.1.0 or 2.0.0 ?
    for m in service['service'].contents[layername].metadataUrls:
        mdurl = m['url']
        # check first that the url exists
        r = requests.head(mdurl)
        if r.status_code != 200:
            ret['problems'].append(f"metadataurl at {mdurl} doesn't seem to exist (returned code {r.status_code})")
        tasklogger.debug(f"{mdurl} -> {r.status_code}")
        mdformat = m['format']
        if mdurl.startswith(localdomain):
            if mdformat == 'text/xml' and "formatters/xml" in mdurl:
            # XXX find the uuid in https://geobretagne.fr/geonetwork/srv/api/records/60c7177f-e4e0-48aa-922b-802f2c921efc/formatters/xml
                localmduuids.add(mdurl.split('/')[7])
            if mdformat == 'text/html' and "datahub/dataset" in mdurl:
            # XXX find the uuid in https://geobretagne.fr/datahub/dataset/60c7177f-e4e0-48aa-922b-802f2c921efc
                localmduuids.add(mdurl.split('/')[5])
            if mdformat == 'text/html' and "api/records" in mdurl:
            # XXX find the uuid in https://ids.craig.fr/geocat/srv/api/records/9c785908-004d-4ed9-95a6-bd2915da1f08
                localmduuids.add(mdurl.split('/')[7])
            if mdformat == 'text/html' and "catalog.search" in mdurl:
            # XXX find the uuid in https://ids.craig.fr/geocat/srv/fre/catalog.search#/metadata/e37c057b-5884-429b-8bec-5db0baef0ee1
                localmduuids.add(mdurl.split('/')[8])
    # in a second time, make sure local md uuids are reachable via csw
    if len(localmduuids) > 0:
        localgn = msc.conf.get('localgn', 'urls')
        service = msc.owscache.get('csw', '/' + localgn + '/srv/fre/csw')
        csw = service['service']
        csw.getrecordbyid(list(localmduuids))
        tasklogger.debug(csw.records)
        for uuid in localmduuids:
            if uuid not in csw.records:
                ret['problems'].append(f"md with uuid {uuid} not found in local csw")
            else:
                tasklogger.debug(f"md with uuid {uuid} exists, title {csw.records[uuid].title}")

    operation = ""
    l = service['service'].contents[layername]
    try:
        if stype == "wms":
            operation = "GetMap"
            if operation not in [op.name for op in service["service"].operations]:
                ret['problems'].append(f"{operation} unavailable")
                return ret
            r = service["service"].getmap(layers=[layername],
                srs='EPSG:4326',
                format='image/png',
                size=(10,10),
                bbox=reduced_bbox(l.boundingBoxWGS84))
            headers = r.info()
            defformat = service["service"].getOperationByName('GetMap').formatOptions[0]
            if headers['content-type'] != defformat:
                ret['problems'].append(f"{operation} succeded but returned format {headers['content-type']} didn't match expected {defformat}")
            # content-length only available for HEAD requests ?
            if 'content-length' in headers and not int(headers['content-length']) > 0:
                ret['problems'].append(f"{operation} succeded but the result size was {headers['content-length']}")

        elif stype == "wfs":
            operation = "GetFeature"
            feat = service["service"].getfeature(typename=[layername],
                srsname=l.crsOptions[0],
#                bbox=reduced_bbox(l.boundingBoxWGS84),
                maxfeatures=1)
            xml = feat.read()
            try:
                root = ET.fromstring(xml.decode())
                first_tag = root.tag.lower()
                if not first_tag.endswith("featurecollection"):
                    ret['problems'].append(f"{operation} succeeded but the first XML tag of the response was {first_tag}")
            except lxml.etree.XMLSyntaxError as e:
                ret['problems'].append(f"{operation} succeeded but didnt return XML ? {xml.decode()}")

        elif stype == "wmts":
            operation = "GetTile"
            (tms, tm, r, c) = find_tilematrix_center(service['service'], layername)
            tile = service["service"].gettile(layer=layername, tilematrixset = tms, tilematrix = tm, row = r, column = c)
            headers = tile.info()
            if headers['content-type'] != l.formats[0]:
                ret['problems'].append(f"{operation} succeded but returned format {headers['content-type']} didn't match expected {l.formats[0]}")
            if 'content-length' in headers and not int(headers['content-length']) > 0:
                ret['problems'].append(f"{operation} succeded but the result size was {headers['content-length']}")

    except ServiceException as e:
        if type(e.args) == tuple and "interdit" in e.args[0]:
            ret['problems'].append(f"got a 403 for {operation} on {layername} in {stype} at {url}")
        else:
            ret['problems'].append(f"failed {operation} on {layername} in {stype} at {url}: {e}")
    else:
       tasklogger.debug(f"{operation} on {layername} in {stype} at {url} succeeded")
    return ret
