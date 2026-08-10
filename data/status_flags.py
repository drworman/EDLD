"""
data/status_flags.py — Elite Dangerous Status.json bit-flag constants.

These constants map to the integer bit fields in Status.json `Flags` and
`Flags2`, and to the `GuiFocus` integer values.  Used for vehicle/mode
detection when polling Status.json.

Source: Frontier journal documentation (2026).
"""

# ── Status.json Flags ─────────────────────────────────────────────────────────

FlagsDocked               = 1 << 0   # on a landing pad
FlagsLanded               = 1 << 1   # on planet surface
FlagsLandingGearDown      = 1 << 2
FlagsShieldsUp            = 1 << 3
FlagsSupercruise          = 1 << 4
FlagsFlightAssistOff      = 1 << 5
FlagsHardpointsDeployed   = 1 << 6
FlagsInWing               = 1 << 7
FlagsLightsOn             = 1 << 8
FlagsCargoScoopDeployed   = 1 << 9
FlagsSilentRunning        = 1 << 10
FlagsScoopingFuel         = 1 << 11
FlagsSrvHandbrake         = 1 << 12
FlagsSrvTurret            = 1 << 13  # using turret view
FlagsSrvUnderShip         = 1 << 14  # turret retracted
FlagsSrvDriveAssist       = 1 << 15
FlagsFsdMassLocked        = 1 << 16
FlagsFsdCharging          = 1 << 17
FlagsFsdCooldown          = 1 << 18
FlagsLowFuel              = 1 << 19  # < 25%
FlagsOverHeating          = 1 << 20  # > 100%
FlagsHasLatLong           = 1 << 21
FlagsIsInDanger           = 1 << 22
FlagsBeingInterdicted     = 1 << 23
FlagsInMainShip           = 1 << 24
FlagsInFighter            = 1 << 25
FlagsInSRV                = 1 << 26
FlagsAnalysisMode         = 1 << 27  # HUD in Analysis mode
FlagsNightVision          = 1 << 28
FlagsAverageAltitude      = 1 << 29  # Altitude from Average radius
FlagsFsdJump              = 1 << 30
FlagsSrvHighBeam          = 1 << 31

# ── Status.json Flags2 (Odyssey on-foot) ──────────────────────────────────────

Flags2OnFoot              = 1 << 0
Flags2InTaxi              = 1 << 1   # (or dropship / shuttle)
Flags2InMulticrew         = 1 << 2   # in someone else's ship
Flags2OnFootInStation     = 1 << 3
Flags2OnFootOnPlanet      = 1 << 4
Flags2AimDownSight        = 1 << 5
Flags2LowOxygen           = 1 << 6
Flags2LowHealth           = 1 << 7
Flags2Cold                = 1 << 8
Flags2Hot                 = 1 << 9
Flags2VeryCold            = 1 << 10
Flags2VeryHot             = 1 << 11
Flags2GlideMode           = 1 << 12
Flags2OnFootInHangar      = 1 << 13
Flags2OnFootSocialSpace   = 1 << 14
Flags2OnFootExterior      = 1 << 15
Flags2BreathableAtmosphere = 1 << 16

# ── Status.json GuiFocus ──────────────────────────────────────────────────────

GuiFocusNoFocus           = 0
GuiFocusInternalPanel     = 1   # right-hand panel
GuiFocusExternalPanel     = 2   # left-hand panel
GuiFocusCommsPanel        = 3   # top panel
GuiFocusRolePanel         = 4   # bottom panel
GuiFocusStationServices   = 5
GuiFocusGalaxyMap         = 6
GuiFocusSystemMap         = 7
GuiFocusOrrery            = 8
GuiFocusFSS               = 9
GuiFocusSAA               = 10
GuiFocusCodex             = 11
