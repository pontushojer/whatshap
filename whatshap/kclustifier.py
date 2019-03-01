from copy import deepcopy
from math import floor, ceil
import itertools as it
import logging
from collections import defaultdict
from .core import clustering_DP, ReadSet, Read
import numpy as np
from .testhelpers import string_to_readset
from .phase import find_components
from statistics import mean
import operator
import random

logger = logging.getLogger(__name__)

def clusters_to_haps(readset, clustering, ploidy, coverage_padding = 12, copynumber_max_artifact_len = 1.0, copynumber_cut_contraction_dist = 0.5, single_hap_cuts = False):
	logger.info("   Processing "+str(len(clustering))+" read clusters ...")
	cluster_blocks = []
	# Compute cluster blocks
	if len(clustering) >= ploidy:
		logger.info("   Processing "+str(len(clustering))+" read clusters ...")
		coverage, copynumbers, cluster_blocks, cut_positions = clusters_to_blocks(readset, clustering, ploidy, coverage_padding, copynumber_max_artifact_len, copynumber_cut_contraction_dist, single_hap_cuts)
	else:
		logger.info("   Processing "+str(len(clustering))+" read clusters ... could not create "+str(ploidy)+" haplotypes from this!")
		return []
		
	# Compute consensus blocks
	logger.info("   Received "+str(len(cluster_blocks))+" cluster blocks. Generating consensus sequences ...")

	consensus_blocks = calc_consensus_blocks(readset, clustering, cluster_blocks, cut_positions)
	
	gaps = sum([sum([sum([1 for i in range(len(hap)) if hap[i] == -1]) for hap in block]) for block in consensus_blocks])
	logger.info("   Phased "+str(ploidy)+" haplotypes over "+str(len(readset.get_positions()))+" variant positions, using "+str(len(consensus_blocks))+" blocks with "+str(gaps)+" undefined sites.")
	
	return consensus_blocks

def calc_consensus_blocks(readset, clustering, cluster_blocks, cut_positions, consensus):
	#cluster_consensus = get_cluster_consensus(readset, clustering)

	consensus_blocks = cluster_blocks	
	for i, block in enumerate(consensus_blocks):
		offset = cut_positions[i-1] if i > 0 else 0	
		for j, hap in enumerate(block):
			for pos, clust in enumerate(hap):
			#	consensus_blocks[i][j][pos] = cluster_consensus[clust][offset+pos] if clust != None else -1
				consensus_blocks[i][j][pos] = consensus[offset+pos][clust] if clust != None else -1
				#consensus_blocks[i][j][pos] = consensus[clust][offset+pos] if clust != None else -1
				
	return consensus_blocks

def get_cluster_consensus(readset, clustering):
	# Map genome positions to [0,l)
	index = {}
	rev_index = []
	num_vars = 0
	for position in readset.get_positions():
		index[position] = num_vars
		rev_index.append(position)
		num_vars += 1
		
	# Create consensus matrix
	cluster_consensus = [[{} for j in range(num_vars)] for i in range(len(clustering))]
	
	# Count all alleles
	for c in range(len(clustering)):
		for read in clustering[c]:
			alleles = [(index[var.position], var.allele) for var in readset[read]]
			for (pos, allele) in alleles:
				if allele not in cluster_consensus[c][pos]:
					cluster_consensus[c][pos][allele] = 0
				cluster_consensus[c][pos][allele] += 1
				
	# Compute consensus for all positions and clusters
	for c in range(len(clustering)):
		for pos in range(num_vars):
			alleles = cluster_consensus[c][pos]
			max_count = -1
			max_allele = -1
			for key in alleles:
				if alleles[key] > max_count:
					max_count = alleles[key]
					max_allele = key
			cluster_consensus[c][pos] = max_allele		
	return cluster_consensus


def subset_clusters(readset, clustering,ploidy, sample, genotypes, genotype_soft_cutoff):


	# Map genome positions to [0,l)
	index = {}
	rev_index = []
	num_vars = 0
	
	for position in readset.get_positions():
		index[position] = num_vars
		rev_index.append(position)
		num_vars += 1

	num_clusters = len(clustering)
	print('number of variants: ', num_vars)
	print('number of clusters: ', num_clusters)
	
	#cov_map maps each position to the list of cluster IDS that appear at this position
	cov_positions = defaultdict()
	cov_map = defaultdict(list)
	for c_id in range(num_clusters):
		covered_positions = []
		for read in clustering[c_id]:
			for pos in [index[var.position] for var in readset[read] ]:		
				if pos not in covered_positions:
					covered_positions.append(pos)
		for p in covered_positions:
			cov_map[p].append(c_id)
#	assert(len(cov_map.keys()) == num_vars)
	print("map of clusters at every position computed")
	
	#compute for each position the amount of clusters that 'cover' this position
	for key in cov_map.keys():
		cov_positions[key] = len(cov_map[key])
	cov_positions_sorted = sorted(cov_positions.items(), key=lambda x: x[1], reverse=True)
	
	#restrict the number of clusters at each position to a maximum of 8 clusters with the largest number of reads	
	for key in cov_map.keys():
		largest_clusters = sorted(cov_map[key], key=lambda x: len(clustering[x]), reverse=True)[:8]
		cov_map[key] = largest_clusters

	#create dictionary mapping a clusterID to a pair (starting position, ending position)
	positions = {}
	counter = 0
	for c_id in range(num_clusters):
		read = clustering[c_id][0]
		start = index[readset[read][0].position]
		end = index[readset[read][-1].position]
		for read in clustering[c_id]:
			readstart = index[readset[read][0].position]
			readend = index[readset[read][-1].position]
			if (readstart < start):
				start = readstart
			if (readend > end):
				end = readend
		positions[c_id] = (start,end)
	assert(len(positions) == num_clusters)
	print("map of clusters to their read positions computed")

	#for every cluster and every variant position, compute the relative coverage
	coverage = [[0]*num_vars for i in range(num_clusters)]
	for c_id in range(num_clusters):
		for read in clustering[c_id]:
			for pos in [index[var.position] for var in readset[read]]:			
				coverage[c_id][pos] += 1
	print("total coverage computed")
	
	coverage_sum = [sum([coverage[i][j] for i in range(num_clusters)]) for j in range(num_vars)]
	
	for c_id in range(num_clusters):
		coverage[c_id] = [((coverage[c_id][i])/coverage_sum[i]) if coverage_sum[i]!= 0 else 0 for i in range(num_vars)]
	assert(len(coverage) == num_clusters)
	assert(len(coverage[0]) == num_vars)
	print("relative coverage computed")
	
	#compute the consensus sequences for every variant position and every cluster for integrating genotypes in the DP
#	consensus = get_cluster_consensus(readset, clustering)
	consensus = get_cluster_consensus_local(readset, clustering, cov_map, positions)
	print("consensus sequences computed")

	geno_map = defaultdict(list)
	counter = 0
	for pos in range(num_vars):
		c_ids = sorted(cov_map[pos])
		c_tuples = sorted(list(it.combinations_with_replacement(c_ids, ploidy)))
		geno_tuples = [tup for tup in c_tuples if (compute_tuple_genotype(consensus,tup, pos) == genotypes[pos])]
		if (len(geno_tuples) == 0):
			#TODO add option to use the next best genotypes if also the next list is empty
			geno_tuples = [tup for tup in c_tuples if (compute_tuple_genotype_soft(consensus,tup, pos, genotypes[pos]) == 1)]
		geno_map[pos] = geno_tuples
	print("No cluster with fitting genotype: ", counter)

	#perform the dynamic programming to fill the scoring matrix (in Cython to speed up computation)
	scoring = clustering_DP(num_vars,clustering,coverage, positions, cov_map, ploidy, genotypes, consensus, geno_map)
	
	#start the backtracing
	path = []	
	#find the last column that contains a minimum other than INT_MAX (1000000, respectively) 
	start_col = find_backtracing_start(scoring, num_vars)
	print("starting in column: ", start_col)
	last_min_idx = min((val, idx) for (idx, val) in enumerate([i[0] for i in scoring[start_col]]))[1]

	#instead of using all tuples, compute only the tuples relevant for the position start_col
	clusters_tuples = geno_map[start_col]
	conf_clusters_tuples = list(it.chain.from_iterable(sorted(list(set(it.permutations(x)))) for x in clusters_tuples))

	path.append(conf_clusters_tuples[last_min_idx])
	#append stored predecessor
	for i in range(start_col,0,-1):
		pred = scoring[i][last_min_idx][1]
		#compute variants relevant for position pred
		tups = geno_map[i-1]	
		conf_tups = list(it.chain.from_iterable(sorted(list(set(it.permutations(x)))) for x in tups))

		path.append(conf_tups[pred])
		last_min_idx = pred
	#path has been assembled from the last column and needs to be reversed
	path.reverse()
	assert(len(path) == start_col+1)
	
	#determine cut positions: Currently, a cut position is created every time a path changes the used cluster from one position to the next
#	cut_positions = [len(readset.get_positions())-1]
	cut_positions = []
	for i in range(len(path)-1):
		dissim = 0
		for j in range(0,ploidy):
			#if (i < len(path) -2):
#				if path[i][j] != path[i+1][j] and path[i][j] != path[i+2][j]:
#					dissim +=1
#			else:
#				if path[i][j] != path[i+1][j]:
#					dissim += 1
			if path[i][j] != path[i+1][j]:
				dissim += 1
		if (dissim >= 1):
			cut_positions.append(i)
	print("cut positions: ", cut_positions)
	
	#experimental: Computing longer blocks and discarding cut positions close to each other
#	cuts = []
#	for c in range(len(cut_positions)-2):
#		dissim = 0
#		current = cut_positions[c]
#		next = cut_positions[c+1]
#		prev = cut_positions[c-1]		
#		for j in range(0,ploidy):
#			if path[current][j] != path[next][j]:
#				dissim += 1
#		if (dissim == 1):
#			dist_bwd = current - prev
#			dist_fwd = cut_positions[c+2] - next
#			if dist_bwd < 4 or dist_fwd < 4:
#				cuts.append(cut_positions[c])
#	cut_positions = cuts[:]
#	print("cut positions after: ", cut_positions)

	#divide path of clusters into <ploidy> separate paths
	haps = []
	for i in range(ploidy):
		temp = [tup[i] for tup in path]
		haps.append(temp)
	assert(len(haps) == ploidy)

	#for testing purposes: compute paths by randomly connecting clusters
#	haps = [[] for i in range(ploidy)]
#	for pos in range(num_vars):
#		possible_clusters = cov_map[pos]
#		for i in range(ploidy):
#			random_cluster = random.choice(possible_clusters)
#			haps[i].append(random_cluster)
#	assert(len(haps[0]) == num_vars)

	# Return cluster blocks: List of blocks, each blocks ranges from one cut position to the next and contains <ploidy> sequences
	# of cluster ids that indicate which cluster goes to which haplotype at which position.
	cluster_blocks = []
	old_pos = 0
	for cut_pos in cut_positions:
		cluster_blocks.append([hap[old_pos:cut_pos] for hap in haps])
		old_pos = cut_pos
	if (len(cut_positions) == 0):
		last_cut = 0
	else:	
		last_cut = cut_positions[len(cut_positions)-1]
	cluster_blocks.append([hap[last_cut:] for hap in haps])
	assert(len(cluster_blocks) == len(cut_positions)+1)

	consensus_blocks = calc_consensus_blocks(readset, clustering, cluster_blocks, cut_positions, consensus)

	haplotypes = []
	for i in range(ploidy):
		hap = ""
		alleles_as_strings = []
		for block in consensus_blocks:
			for allele in block[i]:
				if allele == -1:
					alleles_as_strings.append("n")
				else:
					alleles_as_strings.append(str(allele))
		hap = hap.join(alleles_as_strings)
		haplotypes.append(hap)	

	#write new VCF file	
	superreads, components = dict(), dict()
	
	accessible_positions = sorted(readset.get_positions())
#	accessible_positions = local_positions
	cut_positions = []
	overall_components = {}
	last_cut = 0
	for haploblock in consensus_blocks[:len(consensus_blocks)-1]:
		next_cut = last_cut + len(haploblock[0])
		cut_positions.append(accessible_positions[next_cut])
		
		for pos in range(last_cut, next_cut):
			overall_components[accessible_positions[pos]] = accessible_positions[last_cut]
			overall_components[accessible_positions[pos]+1] = accessible_positions[last_cut]
		last_cut = next_cut
	components[sample] = overall_components
	readset = ReadSet()
	for i in range(ploidy):
		read = Read('superread {}'.format(i+1), 0, 0)
		# insert alleles
		for j,allele in enumerate(haplotypes[i]):
			if (allele=="n"):
				continue
			allele = int(allele)
			qual = [10,10]
			qual[allele] = 0
			read.add_variant(accessible_positions[j], allele, qual)
		readset.add(read)

	superreads[sample] = readset

	return(cut_positions, cluster_blocks, components, superreads, coverage, path)


def get_cluster_consensus_local(readset, clustering, cov_map, positions):

	# Map genome positions to [0,l)
	index = {}
	rev_index = []
	num_vars = 0
	for position in readset.get_positions():
		index[position] = num_vars
		rev_index.append(position)
		num_vars += 1
		
#	cluster_consensus = []
#	for c in range(len(clustering)):
#		row = defaultdict(list)
#		consensus = defaultdict(int)
#		for read in clustering[c]:
#			for (pos, allele) in [(index[var.position], var.allele) for var in readset[read]]:
#				
#				row[pos][0] += allele
#				row[pos][1] += 1
#		for key in row.keys():
#			max_allele = row[key][0]/row[key][1]
#			if max_allele < 0.5:
#				consensus[key] = 0
#			else:
#				consensus[key] = 1
#		del row
#		cluster_consensus.append(consensus)

#	cluster_consensus = [[{} for j in range(num_vars)] for i in range(len(clustering))]						
#
#	for c in range(len(clustering)):
#		for read in clustering[c]:
#			alleles = [(index[var.position], var.allele) for var in readset[read]]
#			for (pos, allele) in alleles:
#				if allele not in cluster_consensus[c][pos]:
#					cluster_consensus[c][pos][allele] = 0
#				cluster_consensus[c][pos][allele] += 1
#				
#	# Compute consensus for all positions and clusters
##	for c in range(len(clustering)):
##		#for pos in range(positions[c][0], positions[c][1]+1):
##		for read in clustering[c]:
##			for pos in [index[var.position] for var in readset[read]]:
#
#
#	
#	for c in range(len(clustering)):
#		for pos in range(num_vars):
#			alleles = cluster_consensus[c][pos]
#			max_count = -1
#			max_allele = -1
#			for key in alleles:
#				if alleles[key] > max_count:
#					max_count = alleles[key]
#					max_allele = key
#			cluster_consensus[c][pos] = max_allele	

	cluster_consensus = []
	for pos in range(num_vars):
		if (pos%1000 == 0):
			print("computing consensus for position: ", pos)
		newdict = defaultdict()
		for c in cov_map[pos]:
			allele0, allele1 = 0,0
			for read in clustering[c]:
				alleles = [(index[var.position], var.allele) for var in readset[read]]
				#todo: get read[position].allele directly without iterating through every var in read?
				for (posi, allele) in alleles:	
					if (posi == pos):				
						if allele == 1:
							allele1 += 1
						else:
							allele0 += 1			
			
			max_allele = 0
			if (allele1 > allele0):	
				max_allele = 1	
			else:
				max_allele = 0
			newdict[c] = max_allele
		cluster_consensus.append(newdict)
	
	return cluster_consensus


def compute_tuple_genotype(consensus,tup, var):
	genotype = 0
	for i in tup:
		#allele = consensus[i][var]
		allele = consensus[var][i]
		genotype += allele
	return(genotype)

def compute_tuple_genotype_soft(consensus,tup, var, geno):
	genotype = 0
	for i in tup:
		allele = consensus[var][i]
		#allele = consensus[i][var]
		genotype += allele
	res = max((geno-genotype),(genotype-geno))
	return(res)

def find_backtracing_start(scoring, num_vars):
	minimum = 1000000
	last_col = num_vars-1
	res = False
	for i in scoring[last_col]:
		if i[0] < minimum:
			res=True
	if res:
		return(last_col)
	else:
		return(find_backtracing_start(scoring,last_col-1))
						
			
def clusters_to_blocks(readset, clustering, ploidy, coverage_padding = 12, copynumber_max_artifact_len = 1.0, copynumber_cut_contraction_dist = 0.5, single_hap_cuts = False):
	# Sort a deep copy of clustering
	clusters = sorted(deepcopy(clustering), key = lambda x: min([readset[i][0].position for i in x]))
	readlen = avg_readlength(readset)
	
	# Map genome positions to [0,l)
	index = {}
	rev_index = []
	num_vars = 0
	for position in readset.get_positions():
		index[position] = num_vars
		rev_index.append(position)
		num_vars += 1

	# Get relative coverage for each cluster at each variant position
	coverage = calc_coverage(readset, clusters, coverage_padding, index)
	logger.info("      ... computed relative coverage for all clusters")

	# Assign haploid copy numbers to each cluster at each variant position
	copynumbers = calc_haploid_copynumbers(coverage, num_vars, ploidy)
	logger.info("      ... assigned local copy numbers for all clusters")
	
	# Optimize copynumbers
	postprocess_copynumbers(copynumbers, rev_index, num_vars, ploidy, readlen, copynumber_max_artifact_len, copynumber_cut_contraction_dist)
	
	# Compute cluster blocks
	cut_positions, cluster_blocks = calc_cluster_blocks(readset, copynumbers, num_vars, ploidy, single_hap_cuts)
	logger.info("   Cut positions:")
	print(cut_positions)
	
	return coverage, copynumbers, cluster_blocks, cut_positions

def avg_readlength(readset):
	# Estiamtes the average read length in base pairs
	if len(readset) > 0:
		return sum([read[-1].position - read[0].position for read in readset]) / len(readset)
	else:
		return 0
	
def calc_coverage(readset, clustering, padding, index):
	# Determines for every variant position the relative coverage of each cluster. 
	# "Relative" means, that it is the fraction of the total coverage over all clusters at a certain position
	num_vars = len(index)
	coverage = [[0]*num_vars for i in range(len(clustering))]
	for c_id in range(0, len(clustering)):
		read_id = 0
		for read in clustering[c_id]:
			start = index[readset[read][0].position]
			end = index[readset[read][-1].position]
			for pos in range(start, end+1):
				coverage[c_id][pos] += 1
	
	coverage_sum = [sum([coverage[i][j] for i in range(len(clustering))]) for j in range(num_vars)]
	for c_id in range(0, len(clustering)):
		coverage[c_id] = [sum(coverage[c_id][max(0, i-padding):min(i+padding+1, num_vars)]) / sum(coverage_sum[max(0, i-padding):min(i+padding+1, num_vars)]) for i in range(num_vars)]
	
	# cov[i][j] = relative coverage of cluster i at variant position j
	return coverage

def calc_haploid_copynumbers(coverage, num_vars, ploidy):
	result = deepcopy(coverage)
	
	for pos in range(num_vars):
		# Sort relative coverages in descending order, keep original index at first tuple position
		cn = sorted([(i, coverage[i][pos]) for i in range(len(coverage))], key = lambda x: x[1], reverse=True)

		# Only look at k biggest values (rest will have ploidy 0 anyways): Only neighbouring integers can be optimal, otherwise error > 1/k
		possibilities = [[floor(cn[i][1]*ploidy), ceil(cn[i][1]*ploidy)] for i in range(ploidy)]
		min_cost = len(coverage)
		min_comb = [1]*ploidy
		for comb in it.product(*possibilities):
			if sum(comb) <= ploidy:
				cur_cost = sum([abs(comb[i]/ploidy - cn[i][1]) for i in range(ploidy)])
				if cur_cost < min_cost:
					min_cost = cur_cost
					min_comb = comb
		for i in range(ploidy):
			cn[i] = (cn[i][0], min_comb[i])
		for i in range(ploidy, len(cn)):
			cn[i] = (cn[i][0], 0)

		# Sort computed copy numbers by index
		cn.sort(key = lambda x: x[0])
		new_cov = [cn[i][1] for i in range(len(cn))]
		
		# Write copy numbers into result
		for c_id in range(len(cn)):
			result[c_id][pos] = cn[c_id][1]
	
	return result

def postprocess_copynumbers(copynumbers, rev_index, num_vars, ploidy, readlen, artifact_len, contraction_dist):
	# Construct intervals of distinct assignments, start with first interval
	start = 0
	interval = []
	intervals = []
	for i in range(len(copynumbers)):
		for j in range(copynumbers[i][0]):
			interval.append(i)
	interval.sort() # Sorted multiset of clusters present at the start
	
	for pos in range(1, num_vars):
		# Create multiset of present clusters for current position
		current = []
		for i in range(len(copynumbers)):
			for j in range(copynumbers[i][pos]):
				current.append(i)
		current.sort()
		if current != interval:
			# if assignment changes, append old interval to list and open new one
			intervals.append((start, pos, deepcopy(interval)))
			start = pos
			interval = current
	# Append last opened interval to list
	intervals.append((start, num_vars, interval))
	logger.info("      ... divided variant location space into "+str(len(intervals))+" intervals")
	
	# Phase 1: Remove intermediate deviation
	if artifact_len > 0.0:
		i = 0
		while i < len(intervals):
			to_merge = -1
			for j in range(i+1, len(intervals)):
				if intervals[i][2] == intervals[j][2]:
					len1 = intervals[i][1] - intervals[i][0]
					len2 = intervals[j][1] - intervals[j][0]
					gap = intervals[j][0] - intervals[i][1]
					gaplen = rev_index[intervals[j][0]] - rev_index[intervals[i][1]]
					if len1 > 2*gap and len2 > 2*gap and gaplen < readlen * artifact_len:
						to_merge = j
						break
			if to_merge > i:
				#print("merging interval "+str(i)+": "+str(intervals[i])+" with interval "+str(to_merge)+": "+str(intervals[to_merge]))
				intervals = intervals[:i] + [(intervals[i][0], intervals[to_merge][1], intervals[i][2])] + intervals[to_merge+1:]
				for k in range(intervals[i][0]+1, intervals[i][1]):
					for l in range(len(copynumbers)):
						copynumbers[l][k] = copynumbers[l][intervals[i][0]]
			else:
				i += 1
		logger.info("      ... reduced intervals to "+str(len(intervals))+" by removing intermediate artifacts")
	
	# Questionable: Close k-1-gaps
	if False:
		i = 0
		while i < len(intervals) - 1:
			set1 = set(intervals[i][2])
			set2 = set(intervals[i+1][2])
			#print(str(i)+" int1="+str(intervals[i][2])+" int2="+str(intervals[i+1][2]))
			if set1 >= set2 and len(intervals[i][2]) == len(intervals[i+1][2]) + 1:
				intervals = intervals[:i] + [(intervals[i][0], intervals[i+1][1], intervals[i][2])] + intervals[i+2:]
				for k in range(intervals[i][0]+1, intervals[i][1]):
					for l in range(len(copynumbers)):
						copynumbers[l][k] = copynumbers[l][intervals[i][0]]
			else:
				i += 1
		logger.info("      ... reduced intervals to "+str(len(intervals))+" by extending intervals to uncovered sites")
			
	# Phase 2: Remove intervals with less than 1*read_length
	if contraction_dist > 0.0:
		i = 0
		while i < len(intervals):
			to_merge = -1
			for j in range(i+2, len(intervals)):
				if rev_index[intervals[j][0]] - rev_index[intervals[i][1]] <= readlen * contraction_dist:
					to_merge = j
				else:
					break
			if to_merge > i:
				middle = (intervals[to_merge][0] + intervals[i][1]) // 2
				#print("merging interval "+str(i)+": "+str(intervals[i])+" with interval "+str(to_merge)+": "+str(intervals[to_merge]))
				intervals = intervals[:i] + [(intervals[i][0], middle, intervals[i][2]), (middle, intervals[to_merge][1], intervals[to_merge][2])] + intervals[to_merge+1:]
				for k in range(intervals[i][0]+1, intervals[i][1]):
					for l in range(len(copynumbers)):
						copynumbers[l][k] = copynumbers[l][intervals[i][0]]
				for k in range(intervals[i+1][0], intervals[i+1][1]-1):
					for l in range(len(copynumbers)):
						copynumbers[l][k] = copynumbers[l][intervals[i+1][1]-1]
			else:
				i += 1
		logger.info("      ... reduced intervals to "+str(len(intervals))+" by shifting proximate interval bounds")
	
def calc_cluster_blocks(readset, copynumbers, num_vars, ploidy, single_hap_cuts = False):
	# Get all changes for each position
	num_clust = len(copynumbers)
	
	# For each position: Get clusters which increase/decrease their copynumber right here. Position 0 contains all initial clusters as increasing.
	increasing = []
	decreasing = []
	increasing.append([c for c in range(num_clust) if copynumbers[c][0] > 0])
	decreasing.append([])
	for pos in range(1, num_vars):
		increasing.append([c for c in range(num_clust) if copynumbers[c][pos-1] < copynumbers[c][pos]])
		decreasing.append([c for c in range(num_clust) if copynumbers[c][pos-1] > copynumbers[c][pos]])
		
	# Layout the clusters into haplotypes and indicate the actual set of cut positions
	cut_positions = []
	haps = [[None]*num_vars for i in range(ploidy)]
	
	# Usually, if a cluster increased in copynumber, i.e. from 1 to 2, then there is a potential block border. The same case is a decrease in copynumber.
	# What really forces a new block is, if the copynumber developes like this: x -> y -> z with 0 < x < y > z > 0, i.e. an increase, followed by a decrease. 
	# In this case it is unclear, how the haplotypes from copynumber x match the ones from copynumber z. So we need to cut, either for the shift from x to y 
	# or from y to z or in between. The opposite case (0 < x > y < z > 0, y > 0) has the same problem. Consecutive increases (x < y < z) or decreases (x > y > z)
	# force no problems. We therefore track for each cluster, if at the current position it is allowed to increase or decrease its copynumber.
	increase_disallowed = set()
	decrease_disallowed = set()
	
	# Start with clusters, that are present at position 0
	h = 0
	for c in increasing[0]:
		for i in range(copynumbers[c][0]):
			haps[h][0] = c
			h += 1
	
	# Iterate over all positions
	for pos in range(1, num_vars):
		open_haps = []
		assigned = [0]*num_clust
		for h in range(ploidy):
			c = haps[h][pos-1]
			# If cluster does not decrease or if it decreases, but the new copynumber is not reached yet, just continue with current cluster on h
			if c != None and (c not in decreasing[pos] or assigned[c] < copynumbers[c][pos]):
				haps[h][pos] = c
				assigned[c] += 1
			else:
				# Else, report haplotype slot as open
				open_haps.append(h)
				
		# Assign unmatched cluster copynumbers to remaining, open slots
		i = 0
		for c in range(num_clust):
			for x in range(copynumbers[c][pos] - assigned[c]):
				haps[open_haps[i]][pos] = c
				i += 1
				
		# Determine, whether this position is a new block
		blocking_clusters = 0
		msg = ""
		for h in range(ploidy):
			# Check for the following: If more than one haplotype needs a new block, we have to add this position as a cut position. If it is only one,
			# we can just assume that the old and the new cluster belong together, implied by the other clusters not needing a change.
			# Exception: If a cluster increases or decreases its copynumber without permission, we always cut
			c = haps[h][pos]
			if haps[h][pos-1] == c or c == None or haps[h][pos-1] == None:
				# No cluster change -> nothing to do
				continue
			# Increase number of block forces by one, in all cases.
			blocking_clusters += 1
			if copynumbers[c][pos-1] == 0:
				# new cluster
				msg = msg + "Cluster "+str(c)+" is new and replacing an old cluster. "
				pass
			elif c in increasing[pos] and c in increase_disallowed:
				# copynumber increases, but c already had a decrease before
				msg = msg + "Cluster "+str(c)+" is increasing, but has decresed since the last cut. "
				blocking_clusters += ploidy
			elif c in decreasing[pos] and c in decrease_disallowed:
				# copynumber increases, but c already had a decrease before
				msg = msg + "Cluster "+str(c)+" is decreasing, but has incresed since the last cut. "
				blocking_clusters += ploidy
			else:
				msg = msg + "Cluster "+str(c)+" is in/decreasing ("+str(copynumbers[c][pos-1])+","+str(copynumbers[c][pos])+") "
		
		if (blocking_clusters <= 1 and not single_hap_cuts) or blocking_clusters == 0:
			#if blocking_clusters == 1:
			#	print("Potential cut at pos="+str(pos)+": " + msg + "But single discontinued cluster can be resolved.")
			# No block, but disallow increase/decrease for clusters with changed copynumber
			for c in range(num_clust):
				if c in increasing[pos] and copynumbers[c][pos-1] > 0:
					decrease_disallowed.add(c)
				elif c in decreasing[pos] and copynumbers[c][pos] > 0:
					increase_disallowed.add(c)
		else:
			# Add cut positions and remove prohibitions regarding copynumber in/decreases
			#print(msg + "Making a cut.")
			cut_positions.append(pos)
			decrease_disallowed.clear()
			increase_disallowed.clear()
	
	# Return cluster blocks: List of blocks, each blocks ranges from one cut position to the next and contains <ploidy> sequences
	# of cluster ids, which indicat e, which cluster goes to which haplotype at which position.
	cluster_blocks = []
	old_pos = 0
	for cut_pos in cut_positions:
		cluster_blocks.append([hap[old_pos:cut_pos] for hap in haps])
		old_pos = cut_pos
		
	return cut_positions, cluster_blocks