# Sniffing Keysight ECal USB interface using Cynthion

## Environment
To set-up the Python environment, you can use a version of conda.
```console
$ conda env create -f environment.yml
```

You can update a python environment from the [environment](environment.yml) file using
```console
$ conda env update -f environment.yml --prune
```

You can export conda environment to the [environment](environment.yml) file using
```console
$ conda export > environment.yml
```

## ECal states
https://documentation.help/SNP-M937xA/documentation.pdf

```python
set_state(device, 42)  # thru
set_state(device, 40)  # confidence
set_state(device, 36)  # open (a)
set_state(device, 33)  # open (b)
set_state(device, 39)  # short (a)
set_state(device, 45)  # short (b)
set_state(device, 37)  # load
set_state(device, 53)  # offset short
set_state(device, 5)  # impedance 5 (offset open)
set_state(device, 21)  # impedance 6 (offset short)
set_state(device, 38)  # impedance 7 (offset short)
```