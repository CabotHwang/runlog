# Controlled oscillator example

The example script starts, holds, and stops a harmonic force.
It calculates the response from a motion equation. Runlog processes the CSV file with these results.
This is a numerical example.

## Model

```text
m*x'' + c*x' + k*x = F(t)
k = m*wn^2,  c = 2*zeta*m*wn,  wn = 2*pi*fn
F(t) = F0*sin(2*pi*fdrive*(t-ton))  for ton <= t < toff
F(t) = 0                         otherwise
x(0) = v(0) = 0
```

The [parameter file](../examples/oscillator_case/params.json) contains these values:

| Parameter | Value |
|---|---|
| Mass | 1 kg |
| Natural frequency and drive frequency | 0.2 Hz |
| Damping ratio | 0.05 |
| Force amplitude | 0.015 N |
| Drive interval | 60–240 s |
| Record interval | 0–360 s |
| Time step | 0.05 s (20 Hz) |

The script uses classical RK4 with an integration step of 0.05 s.
The drive starts and stops at whole cycles. Thus, the force is continuous at both boundaries.
The script adds no sensor noise or response envelope.

## Procedure

After package installation, use this command at the root of the repository:

```bash
.venv/bin/python examples/run_oscillator_case.py
```

The script saves the input files in `examples/output/forced_oscillator_input/`.
It imports these files into the dataset at `examples/output/forced_oscillator/`.
It then does the checks, assigns tags, builds the catalog, and prints the query results.
If you use the script again, it replaces the example record.

The generated metadata contains the equation, parameters, initial state, solver, and units.
It also contains hashes of the generator and CSV file.

To make the figure, install the `plot` extra. Then use this command:

```bash
.venv/bin/python examples/plot_record.py
```

The two panels use the same processed record.
The upper panel shows the force. The lower panel shows displacement and segment tags.
The dashed lines show the drive switch times.
The tag command uses only time and displacement, independently of the force schedule.

## Configuration

The [check settings](../examples/oscillator_case/checks.json) select x and v and specify an expected rate of 20 Hz.
They also select the position–velocity integral check.
The 65 s flatline limit permits the initial 60 s rest.
This limit also permits shorter frozen-sensor events to pass.
The check configuration excludes the intentionally constant force channel.

The [tag settings](../examples/oscillator_case/segments.json) use a 10 s window and a minimum steady candidate of 30 s.
These durations contain two and six drive periods, respectively.
The configuration uses the default flatness tolerance.
The activity threshold is 0.005 m, approximately 7.4% of the theoretical steady RMS.
This value is not a measured noise level.

The tag sequence is `quiet → buildup → steady → decay → quiet`.
Centered windows use future samples. Thus, tag boundaries can precede or follow drive switches.
Some transition intervals have no tag.
The `steady` tag describes the amplitude rule. It does not prove physical stability.

## Numerical verification

The [tests](../tests/test_oscillator_example.py) do these checks:

- Compare both states with an independent closed-form solution. Absolute error must be less than 1e-6 m and m/s.
- Confirm fourth-order convergence when the time step decreases by half.
- Confirm that mechanical energy decreases after the drive stops.
- Compare steady RMS with the harmonic transfer-function prediction.
- Test the data pipeline, provenance, and catalog queries.

The [fault-injection example](../examples/quickstart.sh) tests known data errors separately.
