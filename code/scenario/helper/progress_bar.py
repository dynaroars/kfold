import pandas as pd
import tqdm

class ProgressBar:

    def __init__(self, total, unit, desc, csv_path):
        self.pbar = tqdm.tqdm(
            total=total, unit=unit, desc=desc, dynamic_ncols=True, miniters=1,
        )
        self.unit = unit
        self.csv_data = {}
        self.csv_path = csv_path
        self.global_step = 0

    def _update_step(self):
        self.pbar.update(1)
        self.global_step += 1

    def _csv_cell(self, v):
        if hasattr(v, 'detach'):
            return float(v.detach().reshape(-1)[0].cpu())
        return v

    def _append_csv_data(self, **kwargs):
        if self.unit not in self.csv_data:
            self.csv_data[self.unit] = []
        self.csv_data[self.unit].append(self.global_step)
        for k in kwargs:
            if k not in self.csv_data:
                self.csv_data[k] = []
            self.csv_data[k].append(self._csv_cell(kwargs[k]))

    def append_csv(self, **kwargs):
        self._append_csv_data(**kwargs)

    def _format_postfix(self, k, v):
        if hasattr(v, 'detach'):
            v = v.detach()
            if hasattr(v, 'numel') and int(v.numel()) == 1:
                v = float(v.cpu())
            else:
                return str(tuple(int(x) for x in v.shape))
        if isinstance(v, float):
            digits = 6 if any(t in k for t in ('loss', 'psnr')) else 4
            return f'{v:.{digits}f}'
        return v

    def _update_description(self, **kwargs):
        self.pbar.set_postfix(**{
            k: self._format_postfix(k, v) for k, v in kwargs.items()
        })

    def status(self, **kwargs):
        self._update_description(**kwargs)

    def _display(self):
        self.pbar.display()

    def step(self, **kwargs):
        self._update_description(**kwargs)
        self._append_csv_data(**kwargs)
        self._update_step()
        self._display()

    def tick(self, **kwargs):
        self._update_description(**kwargs)
        self._update_step()
        self._display()

    def to_csv(self):
        # close the bar first: it ends the line, and tqdm does not redraw it at exit
        self.pbar.close()
        df = pd.DataFrame(self.csv_data)
        df.to_csv(self.csv_path, index=None)

def create(total, unit, desc, csv_path):
    return ProgressBar(total, unit, desc, csv_path)

if __name__ == '__main__':
    import time
    pbar = ProgressBar(total=10, unit='iteration', desc='demo',
                       csv_path='../../data/csv/test.csv')
    for i in range(10):
        pbar.step(i=i, i2=i**2)
        time.sleep(1)
    pbar.to_csv()
