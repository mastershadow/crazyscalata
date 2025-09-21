# crazyscalata

## classifiche
SELECT a.* FROM arrivi AS a ORDER BY a.ftempo ASC
SELECT a.* FROM arrivi AS a WHERE a.crazy = "SI" ORDER BY a.ftempo ASC
SELECT a.* FROM arrivi AS a WHERE a.sesso = "M" ORDER BY a.ftempo ASC
SELECT a.* FROM arrivi AS a WHERE a.sesso = "F" ORDER BY a.ftempo ASC
SELECT a.* FROM arrivi AS a WHERE a.tipo = "CICLISTA" ORDER BY a.ftempo ASC
SELECT a.* FROM arrivi AS a WHERE a.tipo = "PODISTA" ORDER BY a.ftempo ASC