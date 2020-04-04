'''
Defines the Person class and functions associated with making people.
'''

#%% Imports
import numpy as np # Needed for a few things not provided by pl
import sciris as sc
from . import utils as cvu


# Specify all externally visible functions this file defines
__all__ = ['Person']


class Person(sc.prettyobj):
    '''
    Class for a single person.
    '''
    def __init__(self, pars, uid, age, sex):
        self.uid         = str(uid) # This person's unique identifier
        self.age         = float(age) # Age of the person (in years)
        self.sex         = int(sex) # Female (0) or male (1)
        self.durpars         = pars['dur']  # Store duration parameters

        # Define state
        self.alive          = True
        self.susceptible    = True
        self.exposed        = False
        self.infectious     = False
        self.symptomatic    = False
        self.severe         = False
        self.critical       = False
        self.diagnosed      = False
        self.recovered      = False
        self.dead           = False
        self.known_contact  = False # Keep track of whether each person is a contact of a known positive

        # Keep track of dates
        self.date_exposed      = None
        self.date_infectious   = None
        self.date_symptomatic  = None
        self.date_severe       = None
        self.date_critical     = None
        self.date_diagnosed    = None
        self.date_recovered    = None
        self.date_died         = None

        # Keep track of durations
        self.dur_exp2inf  = None # Duration from exposure to infectiousness
        self.dur_inf2sym  = None # Duration from infectiousness to symptoms
        self.dur_sym2sev  = None # Duration from symptoms to severe symptoms
        self.dur_sev2crit = None # Duration from symptoms to severe symptoms
        self.dur_disease  = None # Total duration of disease, from date of exposure to date of recovery or death

        self.infected = [] #: Record the UIDs of all people this person infected
        self.infected_by = None #: Store the UID of the person who caused the infection. If None but person is infected, then it was an externally seeded infection

        # Set prognoses
        idx = np.argmax(pars['prognoses']['age_cutoffs'] > self.age)  # Index of the age bin to use
        self.symp_prob = pars['prognoses']['symp_probs'][idx]# Probability of developing symptoms
        self.severe_prob = pars['prognoses']['severe_probs'][idx]/self.symp_prob if self.symp_prob > 0 else 0 # Conditional probability of symptoms becoming severe, if symptomatic
        self.crit_prob   = pars['prognoses']['crit_probs'][idx]/self.severe_prob if self.severe_prob > 0 else 0 # Conditional probability of symptoms becoming critical, if severe
        self.death_prob  = pars['prognoses']['death_probs'][idx]/self.crit_prob if self.crit_prob > 0 else 0 # Conditional probability of dying, given severe symptoms
        self.OR_no_treat = pars['prognoses']['OR_no_treat']  # Increase in the probability of dying if treatment not available

        return


    def infect(self, t, bed_constraint=None, source=None):
        """
        Infect this person and determine their eventual outcomes.
            * Every infected person can infect other people, regardless of whether they develop symptoms
            * Infected people that develop symptoms are disaggregated into mild vs. severe (=requires hospitalization) vs. critical (=requires ICU)
            * Every asymptomatic, mildly symptomatic, and severely symptomatic person recovers
            * Critical cases either recover or die

        Args:
            t: (int) timestep
            bed_constraint: (bool) whether or not there is a bed available for this person
            source: (Person instance), if None, then it was a seed infection

        Returns:
            1 (for incrementing counters)
        """
        self.susceptible    = False
        self.exposed        = True
        self.date_exposed   = t

        # Deal with bed constraint if applicable
        if bed_constraint is None: bed_constraint = False

        # Calculate how long before this person can infect other people
        self.dur_exp2inf     = cvu.sample(**self.durpars['exp2inf'])
        self.date_infectious = t + self.dur_exp2inf

        # Use prognosis probabilities to determine what happens to them
        symp_bool = cvu.bt(self.symp_prob) # Determine if they develop symptoms

        # CASE 1: Asymptomatic: may infect others, but have no symptoms and do not die
        if not symp_bool:  # No symptoms
            dur_asym2rec = cvu.sample(**self.durpars['asym2rec'])
            self.date_recovered = self.date_infectious + dur_asym2rec  # Date they recover
            self.dur_disease = self.dur_exp2inf + dur_asym2rec  # Store how long this person had COVID-19

        # CASE 2: Symptomatic: can either be mild, severe, or critical
        else:
            self.dur_inf2sym = cvu.sample(**self.durpars['inf2sym']) # Store how long this person took to develop symptoms
            self.date_symptomatic = self.date_infectious + self.dur_inf2sym # Date they become symptomatic
            sev_bool = cvu.bt(self.severe_prob) # See if they're a severe or mild case

            # CASE 2a: Mild symptoms, no hospitalization required and no probaility of death
            if not sev_bool: # Easiest outcome is that they're a mild case - set recovery date
                dur_mild2rec = cvu.sample(**self.durpars['mild2rec'])
                self.date_recovered = self.date_symptomatic + dur_mild2rec  # Date they recover
                self.dur_disease = self.dur_exp2inf + self.dur_inf2sym + dur_mild2rec  # Store how long this person had COVID-19

            # CASE 2b: Severe cases: hospitalization required, may become critical
            else:
                self.dur_sym2sev = cvu.sample(**self.durpars['sym2sev']) # Store how long this person took to develop severe symptoms
                self.date_severe = self.date_symptomatic + self.dur_sym2sev  # Date symptoms become severe
                crit_bool = cvu.bt(self.crit_prob)  # See if they're a critical case

                if not crit_bool:  # Not critical - they will recover
                    dur_sev2rec = cvu.sample(**self.durpars['sev2rec'])
                    self.date_recovered = self.date_severe + dur_sev2rec  # Date they recover
                    self.dur_disease = self.dur_exp2inf + self.dur_inf2sym + self.dur_sym2sev + dur_sev2rec  # Store how long this person had COVID-19

                # CASE 2c: Critical cases: ICU required, may die
                else:
                    self.dur_sev2crit = cvu.sample(**self.durpars['sev2crit'])
                    self.date_critical = self.date_severe + self.dur_sev2crit  # Date they become critical
                    this_death_prob = self.death_prob * (self.OR_no_treat if bed_constraint else 1.) # Probability they'll die
                    death_bool = cvu.bt(this_death_prob)  # Death outcome
                    if death_bool:
                        dur_crit2die = cvu.sample(**self.durpars['crit2die'])
                        self.date_died = self.date_critical + dur_crit2die # Date of death
                        self.dur_disease = self.dur_exp2inf + self.dur_inf2sym + self.dur_sym2sev + self.dur_sev2crit + dur_crit2die   # Store how long this person had COVID-19
                    else:
                        dur_crit2rec = cvu.sample(**self.durpars['crit2rec'])
                        self.date_recovered = self.date_critical + dur_crit2rec # Date they recover
                        self.dur_disease = self.dur_exp2inf + self.dur_inf2sym + self.dur_sym2sev + self.dur_sev2crit + dur_crit2rec  # Store how long this person had COVID-19

        if source:
            self.infected_by = source.uid
            source.infected.append(self.uid)

        infected = 1  # For incrementing counters

        return infected


    def check_death(self, t):
        ''' Check whether or not this person died on this timestep  '''
        if self.date_died and t == self.date_died:
            self.exposed     = False
            self.infectious  = False
            self.symptomatic = False
            self.severe      = False
            self.critical    = False
            self.recovered   = False
            self.died        = True
            death = 1
        else:
            death = 0

        return death


    def check_symptomatic(self, t):
        ''' Check if an infected person has developed symptoms '''
        if self.date_symptomatic and t >= self.date_symptomatic: # Person is symptomatic - use >= here because we want to know the total number symptomatic at each time step, not new symptomatics
            self.symptomatic = True
            symptomatic = 1
        else:
            symptomatic = 0
        return symptomatic


    def check_severe(self, t):
        ''' Check if an infected person has developed severe symptoms requiring hospitalization'''
        if self.date_severe and t >= self.date_severe: # Symptoms have become bad enough to need hospitalization
            self.severe = True
            severe = 1
        else:
            severe = 0
        return severe


    def check_critical(self, t):
        ''' Check if an infected person is in need of IC'''
        if self.date_critical and t >= self.date_critical: # Symptoms have become bad enough to need ICU
            self.critical = True
            critical = 1
        else:
            critical = 0
        return critical


    def check_recovery(self, t):
        ''' Check if an infected person has recovered '''

        if self.date_recovered and t == self.date_recovered: # It's the day they recover
            self.exposed     = False
            self.infectious  = False
            self.symptomatic = False
            self.severe      = False
            self.critical    = False
            self.recovered   = True
            recovery = 1
        else:
            recovery = 0

        return recovery


    def test(self, t, test_sensitivity):
        if self.infectious and cvu.bt(test_sensitivity):  # Person was tested and is true-positive
            self.diagnosed = True
            self.date_diagnosed = t
            diagnosed = 1
        else:
            diagnosed = 0
        return diagnosed
