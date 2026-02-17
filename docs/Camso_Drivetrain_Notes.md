# Camso Drivetrain Notes

## Overview

Below is a collection of direct observations and verified conventions pertaining to Camso transfercase, for the purposes of adaptation during Camso > BeamNG swap operations. 

## Camso Drivetrain Types

### Camso RWD (Rear Wheel Drive)
- Rear wheel drive variants still use a transfer case, but this transfer case lacks the center differential component.
- Camso RWD transfercase includes a "Camso_TransferCase_RWD_rangebox" transfercase variant parent slot that may or may not be excluded depending on "transfercase_to_adapt" options
- unlike BeamNG RWD conventions, the Camso RWD transfer case defines slots for Camso_driveshaft_rear. This appears to be incompatible with BeamNG convention:
For RWD DIRECT adaptations, we propose to entirely get rid of the Camso child slot section containing Camso driveshaft parts:
> for example, this entire section would be removed:
```
        "slots": [

            ["type", "default", "description"],

            ["Camso_driveshaft_rear", "Camso_driveshaft_rear", "Rear Driveshaft"]

        ],
```
- Completing the adaptation by injecting BeamNG driveshaft names into the corresponding transfercase > powertrain slots.


### Camso FWD (Front Wheel Drive)
- Similar layout to RWD, but does not populate slots with "Camso_driveshaft_<>" parts (the slot tree is there, but entries are commented out). Camso includes a "Camso_TransferCase_FWD_rangebox" transfercase variant parent slot that may or may not be excluded depending on "transfercase_to_adapt" options. Powertrain section is simple, frontDriveShaft gets input from gearbox and is assigned inputindex 1


### Camso AWD 

For all Camso AWD variants; 
AWD variant transfercase .jbeam files are broken into two slots.
The first of these parent slots `"name":"<vehiclename><drivetype>"` contains a child slot for `"Camso_differential_center<>"` where the powertrain section lives.
Within the `"Camso_differential_center<>"` parent slot of `"slotType": "Camso_differential_center"` , there is an additional child slot array that calls front and rear `"Camso_driveshaft<>"`:
```
    "slotType": "Camso_differential_center",
    "slots": [

        ["type","default","description"],

        ["Camso_driveshaft_front","Camso_driveshaft_front","Front Driveshaft"],

        ["Camso_driveshaft_rear","Camso_driveshaft_rear","Rear Driveshaft"]
```
- Other than the BeamNG type "splitshaft", which *does* call one front driveshaft slot, both front and rear driveshafts being defined in a transfercase child slot section was not found in BeamNG AWD transfer case. Considerations need to be taken regarding the differing slot layouts.


- Provided below is a working manually edited (Camso Helical AWD > Pickup) transfercase_adapted "`Camso_differential_center<>`" slot example:
   *"`pickup_camso_transfercase_<>_adapted.jbeam`" parentslot: "`Camso_differential_center<>`"
```
"Camso_differential_center_ec8ba": {
  "information": {"name":"crayenne-moracc Helical Center Differential","value":300},
  "slotType": "Camso_differential_center",

  "variables": [
      ["name", "type", "unit", "category", "default", "min", "max", "title", "description"],
      ["$torquesplit", "range", "", "Gearing", 0.5, 0, 1, "Torque Split", "Power to Rear",
        {
          "subCategory": "Transfer Case",
          "stepDis": 0.01,
          "minDis": 0,
          "maxDis": 100
        }
      ]
    ],
  "controller": [
      ["fileName"]
    ],
  "powertrain": [
      ["type", "name", "inputName", "inputIndex"],
      ["differential", "transfercase", "gearbox", 1, {"diffType":"lsd", "lsdLockCoef":0.4, "lsdRevLockCoef":0.4, "lsdPreload":10.0, "uiName":"Center Differential", "defaultVirtualInertia":0.25, "friction":6.7760915077053}],
      ["shaft", "transfercase_F", "transfercase", 2, {"friction":"0.44", "dynamicFriction":0.00048, "uiName":"Front Output Shaft"}],
    ],
  "transfercase": {"diffTorqueSplit":"$=$torquesplit or 0.50"}
} 
```
  note, this manually adapted transfercase has *no* axle slots; the entire "`Camso_differential_center<>`" child slot section was removed.
  we needed to be cognizant of the capitalization of: "transfercase" - which was NOT the same as "transferCase" within the powertrain arrays. BeamNG seems to use "transfercase" while Camso uses "transferCase"


#### Camso AWD Sub-variants 

> legend: "**Camso Name**": `PowertrainType` with {`ParameterType`} *notes*

- **On-Demand Center Coupling**: `"splitShaft"` with `"splitType": "locked"`
    *may require `camso_dse_drivemodes_<>.jbeam` or generated `electronicSplitShaftLock` controller*

- **Viscous Center Differential**: `"differential"` with `"diffType": "viscous"`

- **Helical Center Differential**: `"differential"` with `"diffType": "lsd"`

- **Advanced Center Differential**: `"differential"` with `"diffType": "lsd"` *Requires `camso_advawd.lua` controller*


### Camso 4WD (Four Wheel Drive)
- no center differential component; straight "Camso_TransferCase_4x4_<>" slot
- Camso_driveshaft_rear as a child slot, Camso 4wd_controller as a child coreSlot
- relevant "powertrain" path is typically rangebox > transferCase (inputIndex 1) > frontDriveShaft (inputIndex 2)
- Has "Camso_4wd_controller" slot to control rangebox.
