"""MapLibre styles for the terrain flyover experiments: one imagery source draped over Mapterhorn terrain."""
import json

IMAGERY = {
    'esri': ('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 256, 19),
    'eox': ('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg', 256, 14),
    'osm': ('https://tile.openstreetmap.org/{z}/{x}/{y}.png', 256, 19),
    'topo': ('https://tile.opentopomap.org/{z}/{x}/{y}.png', 256, 17),
}


def style(name, exaggeration=1.5, hillshade=True):
    url, size, maxz = IMAGERY[name]
    layers = [{'id': 'bg', 'type': 'background', 'paint': {'background-color': '#26381f'}},
              {'id': 'img', 'type': 'raster', 'source': 'img'}]
    if hillshade:
        layers.append({'id': 'hs', 'type': 'hillshade', 'source': 'dem',
                       'paint': {'hillshade-exaggeration': 0.25, 'hillshade-shadow-color': '#000000'}})
    return {'version': 8, 'sources': {
        'img': {'type': 'raster', 'tiles': [url], 'tileSize': size, 'maxzoom': maxz},
        'dem': {'type': 'raster-dem', 'url': 'https://tiles.mapterhorn.com/tilejson.json'}},
        'terrain': {'source': 'dem', 'exaggeration': exaggeration}, 'layers': layers}


if __name__ == '__main__':
    import sys
    print(json.dumps(style(sys.argv[1])))
