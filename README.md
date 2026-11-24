<p align="center"><img src="icon.png" width="128" alt="Slimme Warmtepomp"></p>

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

### Vloersensor controleren

`sensor.slimme_wp_vloer_bron` toont waar de regeling de vloertemperatuur vandaan haalt (`vloersensor` of `retour`), `sensor.slimme_wp_vloer_gemeten` de ruwe gemeten waarde. `sensor.slimme_wp_vloer_geschat` volgt die waarde, maar zakt langzaam weg als de pomp uit staat of tapwater maakt, omdat de leiding dan niet de vloer meet.

## Verbruik, kosten en graaddagen

De integratie houdt zelf per dag, week, maand en jaar bij wat de pomp verbruikt en kost, zonder helpers of YAML-packages:

- **Graaddagen** (`sensor.slimme_wp_graaddagen_dag/week/maand`): hoeveel kouder het was dan de referentietemperatuur (`number.slimme_wp_graaddag_basis`, standaard 18 °C), gebaseerd op de buitentemperatuur van de integratie (niet de sensor van de pomp).
- **kWh per graaddag** (`sensor.slimme_wp_kwh_per_graaddag` en `…_week`): verbruik gedeeld door graaddagen, vergelijkbaar tussen koude en milde dagen. Pas vanaf 0,5 graaddag per dag en 1 per week.
- **Verbruik en kosten** (`sensor.slimme_wp_verbruik_vandaag/week/maand`, `sensor.slimme_wp_kosten_vandaag/week/maand/jaar`): standaard met de vaste prijs `number.slimme_wp_vaste_stroomprijs` (0,23 €/kWh). Zet `switch.slimme_wp_kosten_vaste_prijs` uit om met de prijs van de gekoppelde stroomprijssensor op dat moment te rekenen (dynamisch contract).
- **Draaitijd** vandaag en per start, en het aantal **ontdooicycli** vandaag en in 7 dagen.
- **Slimme regeling aan tegenover uit:** `sensor.slimme_wp_kwh_graaddag_regeling` en `…_schaduw` zijn het gemiddelde kWh per graaddag van de laatste 28 dagen waarop de regeling meer dan de helft van de tijd aan stond, tegenover de dagen waarop hij uit stond. Het aantal dagen zit in de attributen van de sensor `sensor.slimme_wp_setpoint` (`dagen_regeling`, `dagen_schaduw`). Pas bruikbaar na een aantal dagen van elk.

Alles wordt bewaard na een herstart. Het verbruik komt uit dezelfde meting als de energiesensoren (compressor en ventilator, niet de circulatiepomp).

## Vloer als maatstaf (met vloersensor)

Met een echte vloersensor weet de regeling hoeveel warmte de vloer heeft ten opzichte van wat nodig is om de woonkamer op het doel te houden (`sensor.slimme_wp_vloer_warmtetekort`). Is de vloer te koud, dan start de tekort-boost; is de vloer vol, dan stopt de boost en blijft de pomp op laag toerental, ook als de kamer nog even achterloopt. Het doel is steeds de woonkamertemperatuur; de vloer bepaalt hoe hard er gestookt moet worden. "Vol" wordt alleen geloofd als de kamer ook echt reageert (het doel binnen ongeveer 3 uur haalt); klopt het geleerde model niet, dan blijft de boost doorgaan.

## Gedeeltelijk opnieuw aanleren

Zitten er fouten in wat de regeling geleerd heeft (bijvoorbeeld na een nieuwe sensor of veel wijzigingen), dan hoef je niet alles weg te gooien. Stel met `Opnieuw Aanleren Percentage` in hoeveel opnieuw geleerd moet worden (standaard 50%) en druk op `Opnieuw Aanleren Starten`. Dat percentage van het huis- en vloermodel, de avondcorrectie, de stooklijncorrectie en de bijsturing wordt vergeten; de rest blijft. Het model vertrouwt daarna minder op oude gegevens en past zich sneller aan. 100% is een volledige reset, net als de actie `slimme_warmtepomp.reset_model` (met optioneel `percentage`). De frequentietabel, ontdooi- en prijsleren blijven altijd behouden.

## De stooklijn leert zelf bij

Blijft de kamer structureel te koud (of te warm) buiten de tolerantie, gemiddeld over enkele uren, dan schuift de regeling de geleerde stooklijn zelf op voor die buitentemperatuur, in blokken van 3 °C met vloeiende overgang. Geplande dips (prijssturing, uitlopen) binnen de tolerantie tellen niet mee. Zo begint de regeling elke dag op het juiste niveau en zijn er geen extra correcties nodig. Zichtbaar als `sensor.slimme_wp_stooklijn_correctie`, bewaard bij een herstart en gewist bij "model resetten". Er wordt niet geleerd bij een open raam, afwezigheid, handmatig overschrijven, ontdooien of als leren uit staat.

## Zelfcorrectie bij een aanhoudend tekort

Blijft de kamer onder het doel terwijl het setpoint al een tijd hetzelfde is, dan corrigeert de regeling dat zelf: de bijsturing groeit sneller (1 °C per uur per graad tekort, bereik tot +6 °C) zolang de kamer niet al vanzelf opwarmt. Bij te warm gaat het terugdraaien ook sneller. De correctie wordt bewaard bij een herstart. De frequentiegrens (dag en stille uren) blijft gelden: de pomp gaat stapsgewijs hoger, niet in één keer naar maximaal toerental.

## Minimaal setpoint bij verwarmen

Heeft jouw vloer water van 30 °C of meer nodig, maar kiest het geleerde model lagere waarden (en blijft de kamer daardoor te koud), zet dan `Minimaal Setpoint Bij Verwarmen` op bijvoorbeeld 31 (0 = uit). Zolang de kamer onder het doel zit, wordt het setpoint minstens zo hoog. Het setpoint loopt mee met de retour plus het toegestane frequentieverschil, dus de pomp springt niet in één keer naar maximaal toerental. Daarna blijft de pomp op laag toerental aan. Uitlopen (te warm, dure stroom, open raam) gaat voor.

## Tekort-boost (kamer blijft te koud)

Blijft de kamer langer dan de wachttijd te koud, dan wacht de regeling niet op de trage bijsturing maar pakt het krachtig aan:

1. **Boost:** het setpoint gaat net zoveel boven de retour dat de compressor naar de boost-frequentie (standaard 50 Hz) draait, en volgt de stijgende retour. Zo loopt de retour snel op. Met een vloersensor en geleerd model is het eindpunt berekend: de boost stopt als de vloer genoeg warmte heeft (maximaal de maximale watertemperatuur van de pomp). Zonder vloersensor geldt het vaste doel (standaard 30 °C).
2. **Aanhouden:** is het doel bereikt (vloer vol, of zonder vloersensor de doel-retour), dan blijft de pomp op het laagste toerental (bijv. 30 Hz) draaien zodat de temperatuur niet verder oploopt. Zodra de kamer weer op temperatuur is, neemt de gewone regeling het over.
3. **Pauze:** daarna wacht de regeling minstens de pauzetijd voor een volgende boost, om niet steeds te starten.

Prijssturing en geplande stilstand worden overruled zolang er een tekort is. Niet tijdens zomermodus, open ramen of de netlimiet. In de stille uren is het tekort twee keer zo groot nodig. In de stille uren geldt ook de maximale frequentie voor stille uren. Alle waarden zijn number-boxen (`Boost Bij Tekort`, `Boost Wachttijd`, `Boost Doel Retourtemperatuur`, `Boost Frequentie`, `Boost Pauze`), met schakelaar `Tekort Boost Actief` en sensor `binary_sensor.slimme_wp_tekort_boost`.

## Vorstbeveiliging

Bij vorst mag de pomp niet volledig stilvallen (water in leidingen en buitenunit kan bevriezen). De vorstbeveiliging houdt de pomp aan en draaiend op het laagste setpoint:

- **Buiten:** onder `number.slimme_wp_vorst_buiten` (standaard 3 °C). Hij laat pas 15 minuten nadat het weer warmer is los, zodat de pomp niet gaat pendelen.
- **Water:** als de retour 5 minuten onder `number.slimme_wp_vorst_retour` (standaard 8 °C) blijft; hij laat los boven die grens + 1 K.
- **Effect:** de pomp wordt niet uitgezet, ook niet bij thermostaat uit, zomermodus of uitlopen. Staat hij uit, dan gaat hij aan. Het setpoint is `number.slimme_wp_min_setpoint` (standaard 20 °C).
- **Melding en status:** een melding in Home Assistant als de beveiliging de pomp moest inschakelen, en `binary_sensor.slimme_wp_vorstbeveiliging`.
- **Uitzetten:** `switch.slimme_wp_vorstbeveiliging_actief`. In schaduwmodus (regeling niet actief) wordt niets aangestuurd.

### Nooit uitzetten rond een ontdooi

De regeling zet de schakelaar van de pomp niet uit tijdens een ontdooicyclus, kort erna, of kort ervoor: dan blijft er ijs op de verdamper zitten en kan de pomp vastlopen. In plaats daarvan blijft de pomp circuleren op het laagste setpoint en wordt hij pas uitgezet als dat veilig is (reden `wacht_ontdooien`). Dit geldt voor thermostaat uit, zomermodus en uitlopen. Het uitstel geldt ook bij een ijsmelding, en in de laatste `number.slimme_wp_ontdooi_vooraf` minuten (standaard 8) voor de verwachte ontdooi (nadat 3 ontdooicycli zijn geleerd).

## Voorspelling van ontdooien en ijsvorming

- **Voorspelling:** na 3 gemeten ontdooicycli toont `sensor.slimme_wp_volgende_ontdooi` hoeveel minuten het naar verwachting duurt tot de volgende ontdooicyclus (negatief = te laat). De interval volgt de recente cycli.
- **Ijsvorming:** direct na elke ontdooicyclus meet de regeling de COP van de schone verdamper. Daarmee vergelijkt hij de COP tussen de cycli. Hij waarschuwt (`sensor.slimme_wp_ijsvorming` = ok / let_op / ijs, `binary_sensor.slimme_wp_ijsvorming_alarm`) bij:
  - `cop_zakt`: COP onder 70 % van het niveau na het ontdooien;
  - `herstelt_niet`: de COP na het ontdooien zelf is meer dan 20 % lager dan lange tijd geleden;
  - `vaker`: ontdooien komt steeds sneller achter elkaar (interval onder 60 % van normaal);
  - `ontdooit_te_laat`: geen ontdooicyclus terwijl het koud is en de pomp al langer dan 2,2 keer het normale interval draait;
  - `pomp_sensor_koud`: de buitensensor van de pomp is meer dan 4 K kouder (t.o.v. de echte buitentemperatuur) dan direct na het ontdooien (alleen als die sensor is gekoppeld);
  - `ontdooi_zwak`: de coil-temperatuur stijgt tijdens een ontdooi nauwelijks (piek onder 15 °C, of onder de helft van normaal). Eén zwakke ontdooi = `let_op`, twee achter elkaar = `ijs` (alleen met coil-sensor);
  - `coil_koud`: de coil is vlak voor het ontdooien kouder dan −12 °C (veel ijs; alleen met coil-sensor);
  - `kritiek`: COP onder 1,6 gedurende 15 minuten terwijl de compressor draait.

### Coil-sensor (optioneel, aanbevolen)

Koppel in de opties de coil-/verdampertemperatuur van de pomp (bij Tuya vaak `pg_temp`). Die springt tijdens een ontdooi met tientallen graden en is daarmee een snellere ontdooi-detectie dan de watertemperaturen. De piek zegt of de ontdooi het ijs echt wegsmelt: gezond 25–45 °C, ineffectief 0–12 °C (`sensor.slimme_wp_ontdooipiek`). Uit echte data: met een te korte ontdooitijd (2 min) en te lage eindtemperatuur (8 °C) bleef de piek op 0,6–3 °C en vroor de pomp binnen uren dicht. De regeling verandert de ontdooi-instellingen van de pomp nooit zelf; ze waarschuwt alleen.
  Eén reden geeft `let_op`, twee of `kritiek` geeft `ijs`. Bij `ijs` verschijnt (hoogstens elke 12 uur) een melding in Home Assistant. De regeling kan de ontdooi-instellingen van de pomp niet zelf aanpassen: controleer interval, starttemperatuur en maximale ontdooitijd in het bedienpaneel.
- De regeling leert dit relatief aan jouw installatie, er zijn geen vaste natuurkundige drempels, behalve de genoemde percentages. Pas na een paar ontdooicycli is er een referentie.

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

### Frequentietabel leert alleen bij rust (v2.12.0)
De tabel "frequentie per verschil" leert alleen nog als frequentie én verschil (setpoint − retour) de laatste ~8 minuten stabiel waren. Overgangen (bijv. 45 Hz direct na een boost, terwijl de compressor nog terugloopt) worden dus niet meer geleerd.

### Onder de comfortband nooit uitlopen (v2.12.1)
De planner mag alleen uitlopen (compressor uit) zolang de kamer binnen de comfortband zit (setpoint − tolerantie laag). Zit de kamer er al onder, dan blijft de pomp verwarmen, ook als het model denkt dat de vloer warm genoeg is. De stooklijn-correctie leert daarnaast sneller bij (middeling 4 u i.p.v. 6 u, hogere leersnelheid).

### Boost stopt als de vloer vol is (v2.12.2)
Tijdens "tekort aanhouden" stopt de pomp met extra warmte zodra de gemeten vloer minstens 0,5 K warmer is dan het model nodig vindt en de kamer reageert. Voorheen bleef hij aanhouden tot de kamer op setpoint was, waardoor de vloer te veel warmte kreeg en de kamer tot 21,6 °C opliep.

### Haalbaar setpoint en frequentiebegrenzing (v2.12.3)
- Het geleerde setpoint mag niet meer door een te steile handmatige stooklijn worden vastgepind: ondergrens is nu stooklijn − 12 K (was − 6 K).
- De frequentiebegrenzing mag het huis-basisniveau maximaal 2 K boven "retour + toegestaan verschil" laten uitkomen. Een onhaalbaar setpoint (38 °C bij 0 °C buiten) hield de pomp daardoor op 70 Hz terwijl "frequentie begrensd" aan stond.
- Overdag begrenst de regeling op de efficiënte boost-frequentie (50 Hz) zolang de kamer binnen de comfortband zit; eronder mag het volledige bereik (max frequentie dag).

### Frequentie terugregelen en vloer/setpoint-tabel (v2.13.0)
- De pomp ramt zijn frequentie zelf op zolang het verschil setpoint − retour positief blijft. Staat hij boven de toegestane frequentie, dan verkleint de regeling het verschil met 0,15 K per Hz boven de grens (minimaal 0,3 K), zodat hij echt terugloopt.
- De frequentietabel is monotoon: een groter verschil toont nooit een lagere frequentie. Opnieuw aanleren wist (of verkleint) nu ook deze tabel.
- Nieuw attribuut `vloer_setpoint_tabel` (op sensor Setpoint): per buitentemperatuur de vloertemperatuur die de kamer op setpoint houdt en het bijbehorende setpoint naar de warmtepomp. Zichtbaar in dashboard v12.

### Frequentielimiet blijft bij klein tekort (v2.13.1)
De frequentielimiet (efficiënte boost-frequentie, standaard 50 Hz) wordt pas opgeheven als de kamer meer dan 0,8 K onder de comfortband zit (of onder de minimale kamertemperatuur). Een tekort van enkele tienden graad liep eerder door tot 70 Hz.

### Warme vloer: niet harder duwen (v2.13.2)
Is de gemeten vloer (bijna) op het niveau dat het model nodig heeft (tekort ≤ 1 K) en wordt de kamer niet kouder, dan blijft de frequentielimiet ook gelden als de kamer ver onder de band zit. De warmte van de vloer naar de kamer kost uren; harder stoken geeft later alleen overshoot. Onder de minimale kamertemperatuur vervalt de limiet altijd.

### Ontdooipiek werkt weer (v2.14.1)
De regeling meet elke 2 minuten, maar de coil-detectie zocht een stijging van 6 K binnen 100 s en zag daardoor nooit twee samples met een ontdooi ertussen. Sensor Ontdooipiek bleef leeg. Het zoekvenster is nu 150 s.

### Vloer niet te ver laten afkoelen (v2.13.3)
Is de kamer te warm omdat de vloer nog warmte afgeeft, dan liep de pomp eerder helemaal uit ("te warm"). De vloer koelde dan ver onder wat de kamer nodig heeft, en daarna moest hij hard opladen terwijl de kamer onder het setpoint zakte. Nu blijft de pomp zacht (minimale frequentie) doordraaien zolang de gemeten vloer meer dan 0,5 K onder het modelniveau zit en de kamer niet meer dan 1 K boven de bovengrens ligt. Zichtbaar als attribuut `vloer_aanhouden`.

### Tabel buiten / kamer / vloer / setpoint (v2.13.4)
Het attribuut `vloer_setpoint_tabel` toont per buitentemperatuur drie kamerdoelen (dagsetpoint −0,4 / ±0 / +0,6 K): de vloertemperatuur die de kamer daarop houdt en het bijbehorende setpoint naar de warmtepomp.

### Verwacht setpoint komende uren (v2.14.0)
Attribuut `verwacht_setpoint` (sensor Setpoint): voor nu en elke 2 uur tot 12 uur vooruit het kamerdoel, de benodigde vloertemperatuur en het basissetpoint, berekend met de weersvoorspelling en de zon en inclusief de geleerde stooklijn-correctie. Voorverwarmen en uitlopen van de planner komen daar nog bovenop.

### Coil per seconde en plan zichtbaar tijdens ontdooien (v2.15.0)
- Elke wijziging van de coil-sensor wordt tussen twee regelrondes bewaard (event-gedreven). De ontdooipiek is daardoor de echte hoogste waarde van de ontdooi, niet wat de 2-minuten-meting toevallig zag.
- Tijdens ontdooien (en tapwater) blijven Plan, Verwacht buiten, Kamer na bedtijd, Verwachte afkoeling enz. de laatst berekende waarde tonen in plaats van "onbekend".

### Tabel toont ook het berekende setpoint (v2.15.1)
In `vloer_setpoint_tabel` staat per kamerdoel naast `setpoint` (wat naar de pomp gaat, na de ondergrens "Laagste setpoint") nu ook `berekend`: wat de regeling zelf nodig vindt. Staat Laagste setpoint hoger dan het berekende setpoint, dan zie je dat meteen.
