import os
import numpy as np
import re
from pyxtal import pyxtal
from pyxtal.lattice import Lattice
from ase import Atoms
from ase.units import eV, Ang

class GULP():
    """
    This is a calculator to perform structure optimization in GULP
    At the moment, only inorganic crystal is considered
    Args:

    struc: structure object generated by Pyxtal
    ff: path of forcefield lib
    opt: `conv`, `conp`, `single`
    """

    def __init__(self, struc, label="_", path='tmp', ff='reax', \
                 opt='conp', steps=1000, exe='gulp',\
                 input='gulp.in', output='gulp.log', dump=None):

        if isinstance(struc, pyxtal):
            struc = struc.to_ase()

        if isinstance(struc, Atoms):
            self.lattice = Lattice.from_matrix(struc.cell)
            self.frac_coords = struc.get_scaled_positions()
            self.sites = struc.get_chemical_symbols()
        else:
            raise NotImplementedError("only support ASE atoms object")

        self.structure = struc
        self.label = label
        self.ff = ff
        self.opt = opt
        self.exe = exe
        self.steps = steps
        self.folder = path  
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)
        self.input = self.folder + '/' + self.label + input
        self.output = self.folder + '/' + self.label + output
        self.dump = dump
        self.iter = 0
        self.energy = None
        self.stress = None
        self.forces = None
        self.positions = None
        self.optimized = False
        self.cputime = 0
        self.error = False

    def run(self, clean=True):
        self.write()
        self.execute()
        self.read()
        if clean:
            self.clean()

    def execute(self):
        cmd = self.exe + '<' + self.input + '>' + self.output
        os.system(cmd)


    def clean(self):
        os.remove(self.input)
        os.remove(self.output)
        if self.dump is not None:
            os.remove(self.dump)

    def to_ase(self):
        return Atoms(self.sites, scaled_positions=self.frac_coords, cell=self.lattice.matrix)

    def to_pymatgen(self):
        from pymatgen.core.structure import Structure
        return Structure(self.lattice.matrix, self.sites, self.frac_coords)

    def to_pyxtal(self):
        pmg = self.to_pymatgen()
        struc = pyxtal()
        struc.from_seed(pmg)
        return struc

    def write(self):
        a, b, c, alpha, beta, gamma = self.lattice.get_para(degree=True)
        
        with open(self.input, 'w') as f:
            if self.opt == 'conv':
                f.write('opti stress {:s} conjugate nosymmetry\n'.format(self.opt))
            elif self.opt == "single":
                f.write('grad conp stress\n')
            else:
                f.write('opti stress {:s} conjugate nosymmetry\n'.format(self.opt))

            f.write('\ncell\n')
            f.write('{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}\n'.format(\
                    a, b, c, alpha, beta, gamma))
            f.write('\nfractional\n')
            
            symbols = []
            for coord, site in zip(self.frac_coords, self.sites):
                f.write('{:4s} {:12.6f} {:12.6f} {:12.6f} core \n'.format(site, *coord))
            species = list(set(self.sites))

            f.write('\nSpecies\n')
            for specie in species:
                f.write('{:4s} core {:4s}\n'.format(specie, specie))

            f.write('\nlibrary {:s}\n'.format(self.ff))
            f.write('ewald 10.0\n')
            #f.write('switch rfo gnorm 1.0\n')
            #f.write('switch rfo cycle 0.03\n')
            if self.opt != "single":
                f.write('maxcycle {:d}\n'.format(self.steps))
            if self.dump is not None:
                f.write('output cif {:s}\n'.format(self.dump))


    def read(self):
        with open(self.output, 'r') as f:
            lines = f.readlines()
        try: 
            for i, line in enumerate(lines):
                m = re.match(r'\s*Total lattice energy\s*=\s*(\S+)\s*eV', line)
                #print(line.find('Final asymmetric unit coord'), line)
                if m:
                    self.energy = float(m.group(1))

                elif line.find('Job Finished')!= -1:
                    self.optimized = True

                elif line.find('Total CPU time') != -1:
                    self.cputime = float(line.split()[-1])

                elif line.find('Final stress tensor components')!= -1:
                    stress = np.zeros([6])
                    for j in range(3):
                        var=lines[i+j+3].split()[1]
                        stress[j]=float(var)
                        var=lines[i+j+3].split()[3]
                        stress[j+3]=float(var)
                    self.stress = stress

                # Forces, QZ copied from https://gitlab.com/ase/ase/-/blob/master/ase/calculators/gulp.py
                elif line.find('Final internal derivatives') != -1:
                    s = i + 5
                    forces = []
                    while(True):
                        s = s + 1
                        if lines[s].find("------------") != -1:
                            break
                        g = lines[s].split()[3:6]

                        for t in range(3-len(g)):
                            g.append(' ')
                        for j in range(2):
                            min_index=[i+1 for i,e in enumerate(g[j][1:]) if e == '-']
                            if j==0 and len(min_index) != 0:
                                if len(min_index)==1:
                                    g[2]=g[1]
                                    g[1]=g[0][min_index[0]:]
                                    g[0]=g[0][:min_index[0]]
                                else:
                                    g[2]=g[0][min_index[1]:]
                                    g[1]=g[0][min_index[0]:min_index[1]]
                                    g[0]=g[0][:min_index[0]]
                                    break
                            if j==1 and len(min_index) != 0:
                                g[2]=g[1][min_index[0]:]
                                g[1]=g[1][:min_index[0]]

                        G = [-float(x) * eV / Ang for x in g]
                        forces.append(G)
                    forces = np.array(forces)
                    self.forces = forces

                elif line.find(' Cycle: ') != -1:
                    self.iter = int(line.split()[1])

                elif line.find('Final fractional coordinates of atoms') != -1:
                    s = i + 5
                    positions = []
                    species = []
                    while True:
                        s = s + 1
                        if lines[s].find("------------") != -1:
                            break
                        xyz = lines[s].split()[3:6]
                        XYZ = [float(x) for x in xyz]
                        positions.append(XYZ)
                        species.append(lines[s].split()[1])
                    self.frac_coords = np.array(positions)

                elif line.find('Final Cartesian lattice vectors') != -1:
                    lattice_vectors = np.zeros((3,3))
                    s = i + 2
                    for j in range(s, s+3):
                        temp=lines[j].split()
                        for k in range(3):
                            lattice_vectors[j-s][k]=float(temp[k])
                    self.lattice = Lattice.from_matrix(lattice_vectors)
            if np.isnan(self.energy):
                self.error = True
                self.energy = 100000
                print("GULP calculation is wrong, reading------")
        except:
            self.error = True
            self.energy = 100000
            print("GULP calculation is wrong")

def single_optimize(struc, ff, opt="conp", exe="gulp", path="tmp", label="_", clean=True):
    calc = GULP(struc, label=label, path=path, ff=ff, opt=opt)
    calc.run(clean=clean)
    if calc.error:
        print("GULP error in single optimize")
        return None, 100000, 0, True
    else:
        return calc.to_pyxtal(), calc.energy, calc.cputime, calc.error

def optimize(struc, ff, optimizations=["conp", "conp"], exe="gulp", 
            path="tmp", label="_", clean=True):

    time_total = 0
    for opt in optimizations:
        struc, energy, time, error = single_optimize(struc, ff, opt, exe, path, label)
        time_total += time
        if error:
            return None, 100000, 0, True
    return struc, energy, time_total, False


if __name__ == "__main__":

    from pyxtal.crystal import random_crystal

    while True:
        count = 0
        struc = random_crystal(19, ["C"], [16], 1.0)
        if struc.valid:
            break
    calc = GULP(struc, opt="single", ff="tersoff.lib")
    calc.run()
    #calc.clean_up = False
    print(calc.energy)
    print(calc.stress)
    print(calc.forces)

    struc, eng, time, _ = optimize(struc.to_ase(), ff="tersoff.lib")
    print(struc)
    print(eng)
    print(time)
