# Version 3.0 14/09/20
# Authors: Stephen Marsland, Nirosha Priyadarshani, Julius Juodakis, Virginia Listanti

# This is the script that starts AviaNZ. It processes command line options
# and then calls either part of the GUI, or runs on the command line directly.

#    AviaNZ bioacoustic analysis program
#    Copyright (C) 2017--2020

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Cut down by Ysobel Sims, University of Newcastle 2024
# This version is for running on a Raspberry Pi device in the field
import json, shutil, os, sys, argparse
from jsonschema import validate
import util.SupportClasses as SupportClasses
import AviaNZ_batch

# Command line running to run a filter is something like
# python AviaNZ.py -c -b -d "/home/marslast/Projects/AviaNZ/Sound Files/train5" -r "Morepork" -w
parser = argparse.ArgumentParser()
parser.add_argument(
    "-d",
    "--sdir1",
    type=str,
    help="Input sound directory to process",
)
parser.add_argument(
    "-r",
    "--recogniser",
    type=str,
    help="Recogniser name",
)
parser.add_argument("command", nargs="*", help="Command to execute")

args = parser.parse_args()


if getattr(sys, "frozen", False):
    appdir = sys._MEIPASS
else:
    appdir = os.path.dirname(os.path.abspath(__file__))
os.chdir(appdir)

configdir = os.path.expanduser("~/.avianz/")

# if config and bird files not found, copy from distributed backups.
# so these files will always exist on load (although they could be corrupt)
# (exceptions here not handled and should always result in crashes)
if not os.path.isdir(configdir):
    print("Creating config dir %s" % configdir)
    try:
        os.makedirs(configdir)
    except Exception as e:
        print("ERROR: failed to make config dir")
        print(e)
        raise

# pre-run check of config file validity
confloader = SupportClasses.ConfigLoader()
configschema = json.load(open("Config/config.schema"))
learnparschema = json.load(open("Config/learnpar.schema"))
try:
    config = confloader.config(os.path.join(configdir, "AviaNZconfig.txt"))
    validate(instance=config, schema=configschema)
    learnpar = confloader.learningParams(os.path.join(configdir, "LearningParams.txt"))
    validate(instance=learnpar, schema=learnparschema)
    print("successfully validated config file")
except Exception as e:
    print("Warning: config file failed validation with:")
    print(e)
    try:
        shutil.copy2("Config/AviaNZconfig.txt", configdir)
        shutil.copy2("Config/LearningParams.txt", configdir)
    except Exception as e:
        print("ERROR: failed to copy essential config files")
        print(e)
        raise

# check and if needed copy any other necessary files
necessaryFiles = [
    "ListCommonBirds.txt",
    "ListDOCBirds.txt",
    "ListBats.txt",
    "LearningParams.txt",
]
for f in necessaryFiles:
    if not os.path.isfile(os.path.join(configdir, f)):
        print("File %s not found in config dir, providing default" % f)
        try:
            shutil.copy2(os.path.join("Config", f), configdir)
        except Exception as e:
            print("ERROR: failed to copy essential config files")
            print(e)
            raise

# copy over filters to ~/.avianz/Filters/:
filterdir = os.path.join(configdir, "Filters/")
if not os.path.isdir(filterdir):
    print("Creating filter dir %s" % filterdir)
    os.makedirs(filterdir)
for f in os.listdir("Filters"):
    ff = os.path.join("Filters", f)  # Kiwi.txt
    if not os.path.isfile(os.path.join(filterdir, f)):  # ~/.avianz/Filters/Kiwi.txt
        print("Recogniser %s not found, providing default" % f)
        try:
            shutil.copy2(ff, filterdir)  # cp Filters/Kiwi.txt ~/.avianz/Filters/
        except Exception as e:
            print("Warning: failed to copy recogniser %s to %s" % (ff, filterdir))
            print(e)

print("Running AviaNZ batch process")
avianzbatch = AviaNZ_batch.AviaNZ_batchProcess(configdir, args.sdir1, args.recogniser)
print("Batch process complete")
