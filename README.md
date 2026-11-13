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

## Optionele extra functies (v2.1)

Alles hieronder is optioneel: koppel je de sensor niet, dan bestaan de bijbehorende entiteiten niet.

- **Raam/deur open** (`open_sensors`): na `raam_vertraging` minuten (standaard 5) stopt de verwarming (uitlopen, reden `raam_open`). Tijdens open ramen leert het model niet, zodat de huismeting niet vervuild raakt. Bij echte nood (kamer onder minimum) wordt toch verwarmd. Entiteit: `binary_sensor.slimme_wp_raam_open`.
- **Aanwezigheid / vakantie** (`presence_entities`, `holiday_entity`, `return_time_entity`): is iedereen weg (of staat vakantie aan) langer dan `afwezig_vertraging`, dan geldt `afwezig_setpoint`. Met een terugkomsttijd (input_datetime) verwarmt de planner op tijd voor; een handmatige keuze wint altijd. Entiteit: `binary_sensor.slimme_wp_afwezig`.
- **Netimport-limiet** (`grid_power_sensor`, `netimport_limiet` in W, 0 = uit): blijft de import 5 minuten boven de limiet, dan wordt de warmtepomp tijdelijk niet extra belast (max. 45 min, daarna 15 min pauze, vrijgave onder 80 % van de limiet). Piekjes zoals koken worden genegeerd. Entiteit: `binary_sensor.slimme_wp_netlimiet`.
- **COP en starts per dag**: `sensor.slimme_wp_cop_vandaag`, `..._cop_gisteren`, `..._starts_vandaag`, `..._starts_gisteren`. Veel starts per dag betekent korte-cycli; dat kun je met minimale draaitijd verbeteren.
- **Geleerde stooklijn**: attribuut `geleerde_stooklijn` (aanvoertemperatuur bij -5/0/5/10/15 °C buiten), alleen zichtbaar als het model betrouwbaar is.

## Zacht draaien (laag compressortoerental)

De frequentie van de pomp kan niet worden aangestuurd, maar het verschil tussen setpoint en retourtemperatuur wel, en daar bepaalt de pomp zelf zijn toerental uit. De integratie leert per verschil (stappen van 0,5 K) of de compressor blijft draaien en met welke frequentie en welk vermogen. Het *minimale verschil* waarbij de compressor nog draait wordt het vloerverschil. Als er weinig warmte nodig is (kamer op setpoint, geen voorverwarmen) houdt de regeling het setpoint op retour + dat minimum + `modulatie_marge`, zodat de pomp zacht blijft draaien in plaats van hard te draaien en te stoppen. Af en toe (hoogstens elke 2 uur, 30 minuten, alleen als de kamer boven setpoint zit) probeert hij 0,5 K lager om de kennis bij te houden. Zonder geleerde waarde doet de functie niets. Uitzetten kan met `switch.slimme_wp_modulatie_actief`; je ziet het aan `binary_sensor.slimme_wp_zacht_draaien` en de attributen `modulatie_minimaal_verschil` en `modulatie_frequentie_op_minimum` van `sensor.slimme_wp_setpoint`.

## Frequentiegrens (dag en stille uren)

De frequentie van de pomp kan niet worden aangestuurd, maar de integratie leert per verschil tussen setpoint en retour welke frequentie de pomp draait (`frequentie_tabel`, bijvoorbeeld +1 K = 30 Hz, +3 K = 50 Hz, +5 K = 80 Hz). Met `max_freq_dag` en `max_freq_stil` (Hz, 0 = uit) bepaal je hoe hard de pomp mag gaan. Daaruit volgt een maximaal verschil; het setpoint komt dan nooit hoger dan retour + dat verschil. Daarmee kan de pomp overdag kort hard draaien om de retour op te laden (bijvoorbeeld naar 28-29 °C) en daarna met het kleine verschil rustig laag blijven draaien (zie *Zacht draaien*), terwijl hij in de stille uren onder zijn lagere grens blijft.

- De grens verhoogt of verlaagt de instelling in de pomp zelf niet. Staat daar een harde grens (bijvoorbeeld 50 Hz), dan leert de integratie ook niets boven die frequentie. Verhoog hem in het bedienpaneel stapsgewijs.
- De grens beperkt alleen het extra opwarmen: het setpoint dat het huismodel nodig heeft om de temperatuur vast te houden blijft behouden. Bij nood (kamer ruim onder setpoint of onder het minimum) wordt de grens genegeerd.
- Zolang er te weinig gegevens zijn, doet de grens niets. De planner houdt rekening met de grens bij het kiezen van het voorverwarmmoment.
- Zichtbaar via `binary_sensor.slimme_wp_frequentiegrens_actief`.

## Ontdooien leren en buitentemperatuur

- De regeling leert uit de ontdooicycli hoe lang ontdooien duurt, hoe vaak het gebeurt en hoe lang het water daarna nodig heeft om weer stabiel te worden (verschil aanvoer-retour terug binnen 25 % van daarvoor). Na minimaal 3 metingen vervangt de geleerde wachttijd (1,25 x herstel + 0,5 min, tussen 1 en 10 min) de instelling `ontdooi_wachttijd` (standaard 3 min). Tijdens die wachttijd wordt geen COP berekend en leert het huismodel niet. Zichtbaar als attributen `ontdooien` (aantal, duur, interval, herstel) en `ontdooi_wachttijd_min` van `sensor.slimme_wp_setpoint`.
- **Buitentemperatuur:** de verplichte buitensensor stuurt stooklijn, zomermodus en het huismodel. Gebruik daar een echte buitentemperatuur (weerstation, Buienradar of een sensor in de schaduw), niet de sensor op het rooster van de warmtepomp: die bevriest en koelt af door de verdamper. Is de gekozen buitensensor niet beschikbaar, dan gebruikt de integratie de huidige temperatuur van de weerentiteit. De sensor van de pomp zelf kun je optioneel koppelen bij *Buitentemperatuur van de warmtepomp zelf*; die wordt alleen getoond en gebruikt om te leren bij welke temperatuur de pomp ontdooit (`buiten_verschil_unit` en `unit_buiten_temp`).

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
