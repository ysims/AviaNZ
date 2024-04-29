The AviaNZ project can be found at https://github.com/smarsland/AviaNZ. For more information about the project, see http://www.avianz.net.

This fork is designed to provide a version of AviaNZ that can run on a headless Linux device in real-time. That is, audio is directly sent to the software and the software returns a confidence for that audio snippit.

# Installation

1. `git clone https://github.com/ysims/AviaNZ`
2. `pip3 install -r requirements.txt`
3. Build the Cython extensions by running `cd util/ext; python3 setup.py build_ext -i; cd ../..`
4. `python3 AviaNZ.py -d <path/to/sound_files> -r <model_name>`

Where `<path/to/sound_files>` is the path to a folder of wav file and `<model_name>` is the name of the recogniser in the `filters` folder you want to use.

An example is `python3 AviaNZ.py -d sound_files/ -r Bittern`.

# Acknowledgements

Please navigate to the [original repository](https://github.com/smarsland/AviaNZ) to find the authors of this software. The software website is http://www.avianz.net.

If you use the AviaNZ software, please credit the original authors in any papers that you write. An appropriate reference is:

```
@article{Marsland19,
  title = "AviaNZ: A future-proofed program for annotation and recognition of animal sounds in long-time field recordings",
  author = "{Marsland}, Stephen and {Priyadarshani}, Nirosha and {Juodakis}, Julius and {Castro}, Isabel",
  journal = "Methods in Ecology and Evolution",
  volume = 10,
  number = 8,
  pages = "1189--1195",
  year = 2019
}
```

AviaNZ is based on PyQtGraph and PyQt, and uses Librosa and Scikit-learn amongst others.

Development of this software was supported by the RSNZ Marsden Fund, and the NZ Department of Conservation.

The work done in this fork is supported by a NSW Trust Grant and the University of Newcastle.
