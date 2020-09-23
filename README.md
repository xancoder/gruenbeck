# data collector - soft water system - Grünbeck

> This python script collects water consumption data from a "Grünbeck" soft water system and stores into csv file

## Getting Started

### clone git repository

```shell script
git clone https://github.com/xancoder/gruenbeck.git
```

### install dependencies into a virtual environment

```shell script
cd gruenbeck
bash init_venv.sh
```

### modify the config.json

The configuration file `./src/config.json` should be modified to your own needs and settings.

### manually running

```shell script
./venv/bin/python3 ./src/data-collector.py -l
```

## crontab

The Script should be added to a cron job due to store data automatically

```shell script
crontab -e
```

with the following line. Please 

```shell script
0 16 * * MON cd /path/to/gruenbeck && ./venv/bin/python3 ./src/data-collector.py
```

In this example the script starts every week on Monday 1600. The design decision on the weekly run is based on the 14-day memory of the soft water system. More frequent runs would cause more writes and less would leave less time in cause of failures.

NOTE: Imported is that the soft water system has write the measurement of the day before 1600. The default system start this process around 1200.  
