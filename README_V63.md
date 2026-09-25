# DG Deal Finder V63 — Engine + Derivative Bank

Adds a supplementary open engine/spec bank from the `vehicle-makes-models` project.
The upstream dataset publishes 30,390 engine variants across 164 makes and includes:
generation/year range, engine label, fuel, cylinders, displacement cc, power, torque,
transmission, drivetrain, acceleration, top speed, economy and curb weight.

The engine bank is kept separate from the official DfT/DVLA UK vehicle bank so source
provenance is explicit. Year-aware lookup only returns generations whose production range
contains the selected year.

Sidebar action is now:
`BUILD / REFRESH UK + ENGINE BANKS`

Licensing: upstream data is ODbL 1.0 and requires attribution/share-alike for adapted public
databases. The app records source provenance in each engine-bank row.

Validation:
- compile PASS
- AST PASS
- 100/100 targeted regression assertions PASS

The upstream CSV is >4 MB and this build environment could inspect its documented schema but
could not download the raw payload due network restrictions. The deployed app downloads it
directly when the bank-build button is pressed.
