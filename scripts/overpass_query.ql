[out:json][timeout:90];
area["name"="Gdańsk"]["admin_level"="8"]->.a;
(
  way["railway"="tram"](area.a);
  node["railway"="switch"](area.a);
  node["railway"="railway_crossing"](area.a);
  node["railway"="tram_stop"](area.a);
  relation["route"="tram"](area.a);
);
out geom;
