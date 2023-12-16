import spacy
import nltk
import difflib
import multiprocessing as mp
# from WikiAPI import WikiAPI

class NamedEntityRecognizer:
    """
    Named entity recognizer using SpaCy's named entity recognition.

    :param spacy_model: the SpaCy model to use for named entity recognition
        (default = "en_core_web_sm")
    """

    def __init__(self, spacy_model, wiki_api):

        print("+ Setting up named entity recognizer/linker...")
        self._nlp = spacy.load(spacy_model)
        self._entities = []
        self._wiki_api = wiki_api

    def print_entities(self, to_file: str | None = None):
        """
        Prints the entities found in the text.
        """

        for entity in self._entities:
            print(f" Entity: {entity['name']}")
            if 'wikipedia_hit' in entity:
                print(f" Entity Wikipedia hit: {entity['wikipedia_hit']['url']}")

    def process_text(self, text: str, current_entity: str = "", stemmed=True) -> list:
        """
        Processes a text to be able to compare it with other texts.
        Uses Porter stemming and removes stop words.

        :param text: the text to process
        :param current_entity: the current entity to remove from the text
            because it is not relevant for the comparison
        :return process_text
        """

        current_entity_tokenized = nltk.word_tokenize(current_entity)
        text_tokenized = nltk.word_tokenize(text)
        stemmer = nltk.PorterStemmer()
        stop_words = nltk.corpus.stopwords.words('english')

        # Remove stop words and stemmed stop words from tokenized text
        context_words = [word for word in text_tokenized
                         if word not in stop_words
                         and stemmer.stem(word) not in stop_words
                         and word not in current_entity_tokenized
                         and stemmer.stem(word) not in current_entity_tokenized
                         and len(word) > 1
                         ]

        # If entity occurence in text is not specified, return all context words
        # (stemmed or not-stemmed)
        if stemmed:
            return [stemmer.stem(word) for word in context_words]
        return context_words


    def get_context_words(self, text: str, current_entity: str, entity_occurence_in_text: int) -> list:
        """
        Retrieves the context words of a certain entity within a text.
        Uses distance to entity to assign normalized weights

        :param text: the text to get the context words from
        :param current_entity: the entity for which the context words have to be found and weighted
        :param entity_occurence_in_text: the occurence of the entity in the text (-1 means not taking into account - equal weights)

        :returns list({ word: str, weight: str }): list of context words with assigned weights
        """

        text_tokenized = [word.strip('.') for word in nltk.word_tokenize(text)]
        stemmer = nltk.PorterStemmer()
        context_words = self.process_text(text, current_entity, stemmed=False)

         # If entity occurence in text is specified, we want to give more weight to 
        # the context words that are closer to the entity
        entity_occurence = 1
        # TODO: Perhaps use different method to get index of entity in text (supporting entity with multiple words)

        try:
            index_of_entity_in_text = text_tokenized.index(nltk.word_tokenize(current_entity)[0])
        except:
            index_of_entity_in_text = sorted([(i, difflib.SequenceMatcher(None, nltk.word_tokenize(current_entity), word).ratio()) for i, word in enumerate(text_tokenized)], key=lambda x: (x[1], -x[0]), reverse=True)[0][0]
        # index_of_entity_in_text = [i for i, word in enumerate(text_tokenized) if current_entity.split()[0] in word][0]

        while entity_occurence < entity_occurence_in_text:
            try:
                index_of_entity_in_text = text_tokenized.index(nltk.word_tokenize(current_entity)[0])
            except:
                index_of_entity_in_text = sorted([(i, difflib.SequenceMatcher(None, nltk.word_tokenize(current_entity), word).ratio()) for i, word in enumerate(text_tokenized)], key=lambda x: (x[1], -x[0]), reverse=True)[0][0]
            entity_occurence += 1

        # Retrieve the absolute distance of each word to the entity in the text
        word_distance_to_entity = {}
        for idx, word in enumerate(text_tokenized):
            if word != current_entity:
                word_distance_to_entity[word] = abs(idx - index_of_entity_in_text)

        # Noramlize the disatnce of each word based on the highest distance
        # (longer texts have higher distances than shorter texts)
        highest_distance = max(word_distance_to_entity.values())
        norm_word_distance_to_entity = {}
        for word, distance in word_distance_to_entity.items():
            norm_word_distance_to_entity[word] = distance / highest_distance

        # Get the sum of all CONTEXT WORD distances and normalize the distances to add up to 1
        sum_of_context_word_distances = sum([distance for word, distance in norm_word_distance_to_entity.items() if word in context_words])

        # Return the stemmed context words with their normalized weights
        stemmer = nltk.PorterStemmer()
        return [{'word': stemmer.stem(word), "weight": distance / sum_of_context_word_distances } 
                    for word, distance in norm_word_distance_to_entity.items() if word in context_words]

    def extract_entities(self, text: str, exclude_types: list = ['ORDINAL', 'CARDINAL', 'TIME', 'QUANTITY',
                                                                 'MONEY', 'PERCENT']) -> list:
        """
        Extracts entities in the form: [{'name': 'Paris', 'type': 'GPE',
                                         'context': [{ word: 'France', weight: '0.7'},
                                                     { word: 'Eiffel', weight: '0.25'}]
                                        }, ...]
        Uses SpaCy's named entity recognition.
        :param text: the text to extract entities from
        :param keep_types: the types of entities to keep
        """
        doc = self._nlp(text)
        self._entities = []

        # for sent in doc.sents:
            # sent_nlp = self._nlp(sent.text)

        entities_to_add = []
        # Initialize a dict to count occurence of a certain entity
        # within a given text (sentence in this case)
        entity_occurences_in_text = {}

        for ent, idx in zip(doc.ents, range(len(doc.ents))):
            if ent.label_ not in exclude_types:
                if ent.text in entity_occurences_in_text:
                    entity_occurences_in_text[ent.text] += 1
                else:
                    entity_occurences_in_text[ent.text] = 1

                entities_to_add.append({
                    'name': ent.text,
                    'type': ent.label_,
                    'context': self.get_context_words(doc.text, ent.text, entity_occurences_in_text[ent.text])
                })
        self._entities.extend(entities_to_add)

        return self._entities
    
    def disambiguate_entity(self, entity_i, return_dict, return_first=False):

        entity = self._entities[entity_i]

        candidates = self._wiki_api.get_candidates_from_title(entity["name"], limit=15)
        entity['wikipedia_hit'] = {'title': "NO HIT", 'url': "NO HIT", 'score': 0}

        # Dates are very sensitive to mistakes, so we just take the first hit
        if entity['type'] == 'DATE' or return_first:
            url, wikidata = self._wiki_api.get_wikipedia_url_from_id(candidates[0]['pageid'])
            entity['wikipedia_hit'] = {
                    'title': candidates[0]["title"],
                    'page_id': candidates[0]["pageid"],
                    'url': url,
                    'wikidata_id': wikidata,
                    'score': 1
                }
            
            return_dict[entity_i] = entity
            return

        for i, candidate in enumerate(candidates):

            if 'disambiguation' in candidate['title'].lower() or 'list of' in candidate['title'].lower():
                continue

            this_candidate_score_data = {}

            wikipedia_text, url, wikidata_id = self._wiki_api.get_text_url_from_pageid(candidate["pageid"])
            wikipedia_text_processed = self.process_text(wikipedia_text, entity["name"])

            if 'may refer to' in wikipedia_text:
                continue

            # Initialize the similarity value - used to check the similarity between an entity and candidate
            similarity = 0

            # Similarity between context words in text and context words in Wikipedia article title and article
            # similarity += self.jaccard_similarity(context_words, wikipedia_text_processed)
            # this_candidate_score_data['text_similarity'] = self.jaccard_similarity(context_words, wikipedia_text_processed)
            # similarity += self.jaccard_similarity(context_words, wikipedia_title_text_processed) * boost_title_similarity
            # this_candidate_score_data['title_similarity'] = self.jaccard_similarity(context_words, wikipedia_title_text_processed) * boost_title_similarity

            # Boost if there is a full hit (entity name === canadidate title)
            # if self.is_full_hit(entity["name"], candidate["title"]):
            #     similarity += boost_full_hit
            #     this_candidate_score_data['full_hit'] = boost_full_hit


            # Punish if the found candidate is also an entity in the text
            # if candidate["title"] in entity_names and candidate["title"] != entity["name"]:
            #     similarity -= deboost_other_entity
            #     this_candidate_score_data['other_entity'] = -deboost_other_entity

            # Boost first hit
            # if i == 0:
            #     similarity += boost_first_hit
            #     this_candidate_score_data['first_hit'] = boost_first_hit

            # Add similarity of context words in text and context words in Wikipedia article introtext
            # based on the weight of context weights
            context_score = 0
            nr_of_found_context_words = 0
            for context_word in entity["context"]:
                if context_word["word"] in wikipedia_text_processed:
                    context_score += context_word["weight"]
                    # similarity += context_word["weight"]
                    nr_of_found_context_words += 1

            this_candidate_score_data['context_score'] = context_score

            # Boost if entity is same category as first entity hit in Wikipedia article
            # if entity['type'] != 'PERSON':
            #     text_nlp = self._nlp(wikipedia_text)
            #     if text_nlp.ents:
            #         if text_nlp.ents[0].label_ == entity['type']:
            #             similarity += boost_same_category if candidate['title'] == text_nlp.ents[0].text else boost_same_category / 2
            #             this_candidate_score_data['same_category'] = boost_same_category if candidate['title'] == text_nlp.ents[0].text else boost_same_category / 2

            position_boost = 1/(i+1)

            name_title_ratio = difflib.SequenceMatcher(None, entity["name"], candidate["title"]).ratio()
            nice_score = (name_title_ratio + position_boost) * ((nr_of_found_context_words / len(entity["context"])) + context_score + 0.1)
            similarity += nice_score
            # print(candidate["title"], similarity, nr_of_found_context_words / len(entity["context"]), nice_score)
            # Update entity with best candidate
            # print(f"Candidate: {candidate['title']}, score: {similarity}")
            if similarity > entity['wikipedia_hit']['score']:
                entity['wikipedia_hit'] = {
                    'title': candidate["title"],
                    'url': url,
                    'page_id': candidate["pageid"],
                    'score': similarity,
                    'wikidata_id': wikidata_id
                }

        return_dict[entity_i] = entity

    def disambiguate_entities(self, return_first=False):
        """
        Tries to disambiguate entities and find the best Wikipedia article for each entity.
        Uses features:
        1. The similarity between entity context words and Wikipedia article title
        2. The similarity between entity context words and Wikipedia article intro text
        3. Full hit boost if Wikipedia title is equal to entity name
        4. Category boost if entity is same category as first entity hit in Wikipedia article
        5. First hit boost if entity is first hit in results from API
        6. Punish if the found candidate is also an entity in the text

        # TODO: Find a better balance between the weight of features
        """

        manager = mp.Manager()
        return_data = manager.dict()
        pool = mp.Pool(mp.cpu_count())

        for i in range(len(self._entities)):
            pool.apply_async(self.disambiguate_entity, args=(i, return_data, return_first))

        pool.close()
        pool.join()

        for i in range(len(self._entities)):
            self._entities[i] = return_data[i]

        return self._entities

    # ------
    # BELOW ARE ALL DISAMBIGUATION FEATURES
    # ------
    def jaccard_similarity(self, list_1: list, list_2: list) -> float:
        """
        Calculates the Jaccard similarity between two lists of strings.

        :param a: the first list
        :param b: the second list
        """
        # Return 0 if one of the lists is empty
        if len(list_1) == 0 or len(list_2) == 0:
            return 0
        set_1 = set(list_1)
        set_2 = set(list_2)
        return len(set_1.intersection(set_2)) / len(set_1.union(set_2))

    def is_full_hit(self, word_1: str, word_2: str):
        """
        Determines if a word is a full hit with another word
        Full hit = word 1 is equal to word 2 (minus stop words).

        :param word_1: the first word to determine full hit for
        :param word_2: the second word to determine full hit for
        """
        stopwords = nltk.corpus.stopwords.words('english')
        word_1_norm = [word.lower() for word in word_1.split() if word.lower() not in stopwords]
        word_2_norm = [word.lower() for word in word_2.split() if word.lower() not in stopwords]
        return word_1_norm == word_2_norm

# wiki_api = WikiAPI()
# er = NamedEntityRecognizer("en_core_web_sm", wiki_api)
# er.extract_entities(  '""The Birth of Venus"" is a painting by the Italian Renaissance artist Sandro Botticelli. It depicts the goddess Venus, or Aphrodite in Greek mythology, emerging from the sea on a shell. The painting is now housed at the Uffizi Gallery in Florence, Italy.  Botticelli was an influential figure of the Florentine Renaissance and created many other famous works such as ""The Adoration of the')
# entities = er.disambiguate_entities()
# er.print_entities()