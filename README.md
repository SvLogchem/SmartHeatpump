# SmartHeatpump voor Home Assistant

Zelflerende regeling voor warmtepompen met vloerverwarming. Ontwikkeld voor een Alsavo-pomp via Tuya Local, maar bruikbaar voor elke pomp waarvan je de doeltemperatuur als `number` kunt instellen.

## Wat doet het

- **Leert je huis kennen.** Uit de sensoren leert de integratie hoe snel je huis afkoelt, hoe traag de vloer opwarmt en afkoelt en hoeveel de zon bijdraagt. Daaruit rolt vanzelf een eigen stooklijn. Tot het model genoeg data heeft (ca. 2-3 dagen) gebruikt de integratie je handmatige stooklijn en wordt die geleidelijk vervangen.
- **Vloer warm bij bedtijd.** De planner kijkt vooruit (weer, zon, dag/nacht-setpoints) en verwarmt de vloer *voor* je bedtijd extra voor, zodat de kamer na bedtijd niet onder het setpoint zakt en de pomp 's nachts niet hard hoeft te herstellen. Een avondcorrectie leert bij: was de kamer één uur na bedtijd te koud, dan wordt de vloer de volgende dag iets verder opgeladen.
- **Stille uren.** Van bedtijd tot einde van de nacht is de maximale opslag beperkt (`Max Opslag Stille Uren`) en weegt energiegebruik zwaarder (`Voorkeur Stille Uren`).
- **Stroomprijs (optioneel).** Met een prijssensor met voorspelling (Nordpool, EPEX Spot, Frank Energie, ENTSO-E of vergelijkbaar: een lijst met start + prijs in de attributen) wordt warmte verschoven naar goedkopere uren, binnen de comforttolerantie. Zonder voorspelling wordt de huidige prijs vergeleken met de afgelopen 48 uur.
- **Zonnepanelen (optioneel).** Bij overschot telt stroom minder zwaar en kan `Zonnepanelen Boost` extra warmte in de vloer opslaan.
- **Warm tapwater (optioneel).** Vul een vattemperatuursensor en een schakelaar in en je krijgt: minimumtemperatuur, bijladen op goedkope/zonne-uren, een legionellacyclus (standaard wekelijks, 60 °C) en een maximale looptijd als beveiliging. De warmtepomp zelf moet het omschakelen van het ventiel regelen.
- **Compressorbescherming.** Minimale draaitijd en stilstandtijd, geen pendelen door afrondingsfouten (setpoints worden over de tijd gemiddeld), ontdooi-detectie, zomermodus op het 24-uursgemiddelde met hysterese, en een minimale kamertemperatuur als vorstbeveiliging.

## Installatie

HACS > Custom repository > `https://github.com/SvLogchem/SmartHeatpump` > installeren > herstarten > Instellingen > Apparaten & diensten > Integratie toevoegen > *Slimme Warmtepomp*.

Verplicht: kamer- en buitentemperatuur. Voor het leren heb je daarnaast de **retourtemperatuur** (of een vloersensor) en de **aanvoertemperatuur** nodig; de compressorfrequentie maakt het nauwkeuriger. Alles is later aan te passen via *Herconfigureren*.

## Aanbevolen instelling voor "vloer warm om 21:00"

| Instelling | Waarde |
|---|---|
| Bedtijd | 21:00 |
| Setpoint Dag / Nacht | bijv. 21,0 / 20,4 (nacht vanaf 23:00) |
| Tolerantie Te Koud | 0,2-0,3 °C (lager = strikter, maar duurder) |
| Voorkeur Stille Uren | 1-2 |
| Max Opslag Stille Uren | 1,5 °C |

Controleer na een paar dagen de sensoren *Modelvertrouwen*, *Voorspelde Kamer 1u Na Bedtijd* en *Avond Correctie*, en de attributen van *Berekend Setpoint* (o.a. `plan_reden`, geleerde tijdconstanten).

## Entiteiten

- `climate.slimme_wp_thermostaat`: dag/nacht volgt het schema. Handmatig instellen blijft actief tot de volgende dag/nacht-wissel.
- `sensor.slimme_wp_setpoint`: laatst ingestelde watertemperatuur, met veel diagnose in de attributen.
- Overige sensoren: reden van de laatste beslissing, plan, modelvertrouwen, geleerde afkoeltijden, geschatte vloertemperatuur, thermische/elektrische energie (kWh, geschikt voor het energiedashboard), gemiddelde COP.
- Schakelaars om onderdelen uit te zetten: *Regeling*, *Leren*, *Voorverwarmen*, *Prijssturing*, *Tapwatersturing*.
- **Schaduwmodus:** staat *Regeling Actief* uit, dan wordt alles nog steeds berekend en getoond (setpoint, plan, leren), maar er gaat niets naar de warmtepomp of de schakelaar.
- Thermostaatstatus: *Verwarmen* (compressor draait), *Circuleren* (pomp aan, compressor staat stil), *Stand-by* (de regeling heeft de pomp uitgezet), *Uit*.
- Dienst `slimme_warmtepomp.reset_model` wist het geleerde model.

## Upgraden van v1

Alle bestaande entiteiten behouden hun id en unique id, instellingen blijven bewaard. Veranderingen:

- Het dag/nacht-schema gebruikte de **UTC-tijd**; het volgt nu de lokale tijd (in Nederland liep het 1-2 uur achter).
- `Starttijd Dag` en `Eindtijd Dag` deden niets en zijn verwijderd.
- `Waakhond Marge`, `Minimale Draaitijd`, `Bivalente Temperatuur` en `Zonnepanelen Boost` worden nu echt gebruikt (in v1 waren het alleen invoervelden).
- Setpoints worden naar `number` **en** `input_number` correct geschreven en alleen als de waarde verandert.
- Bij ontbrekende sensoren houdt de regeling de laatste stand vast in plaats van met verzonnen waarden (20 °C binnen, 5 °C buiten) te rekenen.
- Zonder `control_mode` in de configuratie werd altijd op retour gestuurd; dit is nu een keuzeveld.

## Beperkingen

- Het model is een twee-knoops model (vloer + kamer) met retour- of vloertemperatuur als vloerproxy. Bij een zeer zware dekvloer met koude avonden kan de regeling doorschieten; zet dan `Tolerantie Te Warm` lager of gebruik een echte vloersensor.
- De prijsvoorspelling wordt herkend aan de vorm van de attributen; controleer in de attributen van *Berekend Setpoint* of er een voorspelling wordt gebruikt.
- Getest met een gesimuleerd huis (zie `tests/`) en met een nagebootste Home Assistant-omgeving; nog niet in een echte installatie.

## Tests

```
pip install pytest
pytest              # ca. 2 minuten; de simulatie draait weken regeltijd
```
