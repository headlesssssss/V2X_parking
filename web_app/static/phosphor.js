// Phosphor Icons — chargement local (sans internet)
var head = document.getElementsByTagName("head")[0];

for (const weight of ["regular", "bold", "fill"]) {
  var link = document.createElement("link");
  link.rel = "stylesheet";
  link.type = "text/css";
  link.href = `/static/phosphor/${weight}/style.css`;
  head.appendChild(link);
}
