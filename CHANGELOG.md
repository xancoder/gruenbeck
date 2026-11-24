# Changelog

All notable changes of this project. The file is generated from the commit messages with git-cliff (see "release" in the README); do not edit it by hand.

## [0.2.0] - 2026-11-24

### Features

- **config:** Read the config file from GRUENBECK_CONFIG and the SMTP password from a systemd credential
- **deploy:** Harden the collector service and limit it to the data and log folders
- **report:** Limit earlier year comparisons
- **mail:** Add data mail preview script
- **mail:** Include HTML statistics and charts in data mail
- **charts:** Render consumption statistics as SVG charts
- **mail:** Include consumption statistics in data mail
- **report:** Compute consumption statistics from stored data
- Validate device clock before storing data
- Add one-time date offset migration
- Detect device rollover across runs
- Add device rollover logging script
- Add configurable analysis input
- Add configurable device timeout
- Add configurable SMTP security
- Add systemd support for Gruenbeck data collector
- Add retry logic for API and email sending
- **analyse:** Add monthly report script
- **collector:** Add function send_mail
- **config:** Add mail property
- **collector:** Write data to csv file
- **config:** Rearrange and add data file properties and sort alphabetically
- **collector:** Integrate http request method to read water consumption
- **gruenbeck:** Add method to read values from the soft water system
- **config:** Add soft water system configuration
- **collector:** Add parameter class
- **gruenbeck:** Add parameter class to read parameter from flat file database
- **assets:** Add more common csv file version of the gruenbeck web server documentation
- **collector:** Add check output folder method
- **collector:** Improve logging messages
- **collector:** Add permanent error logging
- **collector:** Add console logging
- **config:** Add configuration file as optional parameter
- **config:** Add configuration
- **collector:** Add main entry script
- **assets:** Gruenbeck web server documentation

### Bug fixes

- Reject data rows without values and do not resend accepted mails
- **storage:** Keep non-decimal numeric characters as text
- **cli:** Use collection date for data mail statistics
- **device:** Validate consumption values before writing
- Detect pre-rollover runs from stored values
- Fail on large device clock deviations
- Map device values by parameter dates
- Replace versioned config with example config
- Harden systemd setup script
- Relocate systemd unit files
- Fail run when processing or email sending fails
- Write data files atomically
- Always exit on data collector errors
- **collector:** Change email property due to show attachment in email client
- **collector:** Correct ident of mail section
- **collector:** Correct path due to native python run

### Refactoring

- **config:** Remove the migration of paths relative to the working directory
- **analysis:** Name the statistics, aggregate once per file and split output from calculation
- **scripts:** Turn the tools in scripts/ into package commands
- **collector:** Move the run of the data collector out of the cli module
- **report:** Split the report module into calculation, sections, text and HTML
- **device:** Use fixed parameters instead of parameter file
- **storage:** Move yearly data file lookup to storage
- **device:** Use configured retries for device and mail
- **mail:** Send EmailMessage from typed config
- **cli:** Raise errors and set the exit code only in the cli
- Merge the code into the package gruenbeck with commands
- **collector:** Request the 14-day memory explicitly and uncomment all documented parameters
- **collector:** Define handle error function with separate mail sending function
- **collector:** Use SMTP_SSL server instance
- **collector:** Move mux http function into gruenbeck module
- **collector:** Replace parameter with date handling into separate function
- **collector:** Mail handling into separate function
- **collector:** Remove html part from mail function
- **collector:** Rearrange mail function
- **collector:** Move get device data try except block into separate function
- **collector:** Rename variable due to one line
- **collector:** Rename variable and improve doc string
- **collector:** Rename device variables
- **collector:** Remove needless formatted string literals
- **collector:** Rename error variable
- **collector:** Move write data logging message
- **gruenbeck:** Move error handling into run script
- **collector:** Extract data folder function into separate module
- **collector:** Extract configuration file function into separate module
- **collector:** Rename configuration function
- **collector:** Rearrange project structure
- **collector:** No mail configuration handling
- **collector:** Specify type hints of functions
- **collector:** Renaming variables and modify docstring to check_output_folder method
- **collector:** Renaming variables and add docstring to write_data method
- **collector:** Catch parameter xml parse exception
- **gruenbeck:** Throw xml parse exception and remove module logging
- **collector:** Catch parameter file not exist exception
- **gruenbeck:** Throw file not exist exception and remove module logging

### Documentation

- Clarify collector timing and migration recovery
- Move scheduling guide to systemd deploy directory
- **collector:** Update README.md
- **collector:** Update README.md due to rearranged folder structure
- **collector:** Update README.md
- **collector:** Update README.md

### Tests

- Cover configured CSV columns and date patterns
- Characterize collector and gruenbeck behavior
- Make tests cwd-independent
- **gruenbeck-parameter:** Add file tests
- **configuration-file:** Correct imports and add required properties tests
- **data-folder:** Correct imports
- **collector:** Add data folder test
- **collector:** Add configuration file test

### Build

- **collector:** Add pytest to python requirements
- **collector:** Add python requirements

### CI

- Enable more ruff lint rules
- Pin actions to commit SHAs, cancel superseded runs, audit workflows with zizmor
- Run ruff pre-commit hooks from uv
- Type-check scripts and deploy
- Test supported Python versions with analysis extra
- Add GitHub Actions checks and Dependabot

### Style

- Fix Python type checking issues
- Fix Python lint issues
- Format Python code with Black
- **collector:** Replace double quotes with single quotes
- **collector:** Move send main function into data collector module
- **collector:** Remove blank lines

### Miscellaneous

- **mypy:** Check src and tests in strict mode
- **assets:** Remove TSV parameter documentation
- **config:** Add pre-commit hooks
- **config:** Stop versioning src/config.json
- Migrate dependency setup to uv
