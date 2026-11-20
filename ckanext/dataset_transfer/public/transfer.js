let radarSectionOrder = ['dataset', 'creators', 'classification', 'rights', 'funding'];
let radarActiveSection = 0;
let radarReviewedSections = {};
let radarDynamicRowId = 0;
let radarIdentifierVerificationSequence = 0;
let radarIdentifierVerificationCache = {orcid: {}, ror: {}};
let radarIdentifierVerificationRequests = {orcid: {}, ror: {}};
let radarOrganizationSearchSequence = 0;
let radarOrganizationSearchCache = {};
const radarIdentifierDebounceDelay = 500;
const radarIdentifierRequestTimeout = 6000;
const radarOrganizationSearchDelay = 500;
const radarSupportedRights = [
    'CC BY 4.0 Attribution',
    'CC BY-ND 4.0 Attribution-NoDerivs',
    'CC BY-SA 4.0 Attribution-ShareAlike',
    'CC BY-NC 4.0 Attribution-NonCommercial',
    'CC BY-NC-SA 4.0 Attribution-NonCommercial-ShareAlike',
    'CC BY-NC-ND 4.0 Attribution-NonCommercial-NoDerivs',
    'CC0 1.0 Universal Public Domain Dedication',
    'Public Domain Mark 1.0',
    'Attribution License (ODC-By)',
    'Open Database License (ODC-ODbL)',
    'Public Domain Dedication and License (PDDL)',
    'Apache License 2.0',
    'Common Development and Distribution License 1.0',
    'Eclipse Public License 1.0',
    'Eclipse Public License 2.0',
    'GNU General Public License v3.0 only',
    'GNU Lesser General Public License v3.0 only',
    'BSD 2-Clause Simplified License',
    'BSD 3-Clause New or Revised License',
    'MIT License',
    'All rights reserved',
    'Other'
];

$(document).ready(function(){
    update_publish_target_fields();

    /**
     * Click on the next button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let step = $(this).attr("step");
        if( step === "2"){
            if($('#publish_target').val() === "radar"){
                $('#publish_destination_selection').hide();
                $('#publish_step1').hide();
                $('#publish_radar_metadata_step').show();
                initialize_radar_review();
                show_radar_section(radarActiveSection, true);
                $(this).attr("step", "radar-section");
                $('#dataset_transfer_back_btn').show();
                return;
            }
            // console.info($('#token_exist_box').is(':checked'))
            if($('#token_exist_box').val() !== 'true' && !$.trim($('#transfer_api_token_input').val())){
                $('#api_token_input_empty_alert_box').show();
            }
            else{
                $('#publish_step1').hide();
                $('#publish_destination_selection').hide();
                $('#publish_step2').show();
                $(this).attr("step", "3");
            }
        }
        else if (step === "radar-section"){
            let metadata = collect_radar_metadata();
            let errors = errors_for_radar_section(
                validate_radar_metadata_in_browser(metadata),
                radarSectionOrder[radarActiveSection]
            );
            if(errors.length){
                show_radar_validation_errors(errors);
                set_radar_section_status(radarSectionOrder[radarActiveSection], 'attention');
                return;
            }
            clear_radar_validation_errors();
            radarReviewedSections[radarSectionOrder[radarActiveSection]] = true;
            set_radar_section_status(radarSectionOrder[radarActiveSection], 'complete');
            if(radarActiveSection < radarSectionOrder.length - 1){
                show_radar_section(radarActiveSection + 1, true);
            }
            else{
                let allErrors = validate_radar_metadata_in_browser(metadata);
                if(allErrors.length){
                    show_radar_validation_errors(allErrors);
                    return;
                }
                $('#publish_radar_metadata_step').hide();
                $('#publish_step2').show();
                $(this).attr("step", "3").text('Continue');
            }
        }
        else if (step === "3"){          
            if($('#terms_of_usage').prop('checked') !== true || $('#rights_of_use').prop('checked') !== true){
                $("#no_consent_alert_message").show();
            }
            else{
                $('#publish_step1').hide();
                $('#publish_step2').hide();
                if($('#publish_target').val() === 'radar'){
                    render_radar_confirmation(collect_radar_metadata());
                    $('.radar-confirmation').show();
                    $('.luh-confirmation').hide();
                }
                else{
                    $('.radar-confirmation').hide();
                    $('.luh-confirmation').show();
                }
                $('#publish_step3').show();
                $(this).attr("step", "4");
                $(this).hide();
                $('#dataset_transfer_submit').show();
            }
        }
    });

    $('#dataset_transfer_back_btn').click(function(){
        let step = $('#dataset_transfer_next_btn').attr('step');
        if(step === 'radar-section'){
            if(radarActiveSection > 0){
                show_radar_section(radarActiveSection - 1, true);
            }
            else{
                $('#publish_radar_metadata_step').hide();
                $('#publish_destination_selection').show();
                $('#publish_step1').show();
                $('#dataset_transfer_next_btn').attr('step', '2').text('Continue');
                $(this).hide();
            }
        }
        else if(step === '3' && $('#publish_target').val() === 'radar'){
            $('#publish_step2').hide();
            $('#publish_radar_metadata_step').show();
            show_radar_section(radarSectionOrder.length - 1, true);
            $('#dataset_transfer_next_btn').attr('step', 'radar-section');
        }
        else if(step === '3'){
            $('#publish_step2').hide();
            $('#publish_destination_selection').show();
            $('#publish_step1').show();
            $('#dataset_transfer_next_btn').attr('step', '2');
            $(this).hide();
        }
        else if(step === '4'){
            $('#publish_step3').hide();
            $('#publish_step2').show();
            $('#dataset_transfer_submit').hide();
            $('#dataset_transfer_next_btn').show().attr('step', '3');
        }
    });

    
    /**
     * Click on the publish button
     */
     $('#dataset_transfer_submit').click(function(event){
        event.preventDefault();
        if ($(this).data('publishing') === true) {
            return;
        }
        $(this).data('publishing', true);
        $(this).prop('disabled', true);
        $('#publish_step3').hide();
        $('#action_btn_part').hide();
        $('#publish_failed_section').hide();
        $('#publish_result_section').hide();
        $('#publish_step_final').show();
        let dest_url = $('#publish_url').val();        
        let formdata = new FormData();
        formdata.set('package_id', $('#package_id').val());        
        formdata.set('publish_target', $('#publish_target').val());
        formdata.set('api_token', $('#publish_target').val() === 'luh' ? $("#transfer_api_token_input").val() : '');
        formdata.set('save_api_token_box', $('#publish_target').val() === 'luh' && $("#save_api_token_box").prop('checked'));
        formdata.set('token_exist_box', $('#publish_target').val() === 'luh' ? $("#token_exist_box").val() : 'false');
        formdata.set('terms_of_usage', $("#terms_of_usage").prop('checked'));
        formdata.set('rights_of_use', $("#rights_of_use").prop('checked'));
        if($('#publish_target').val() === 'radar'){
            formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));
        }
        add_csrf_token(formdata);
        let req = new XMLHttpRequest();
        req.timeout = 30 * 60 * 1000;
        console.info("Dataset transfer publish request started", dest_url);
        req.onload = function() {
            console.info("Dataset transfer publish response received", req.status, req.responseText);
            let data = parse_publish_response(req.responseText);
            if (req.status >= 200 && req.status < 300 && data && data.success !== false && !data.error) {
                show_publish_success(data);
            }
            else {
                if(data && data.errors && $('#publish_target').val() === 'radar'){
                    $('#publish_step_final').hide();
                    $('#publish_radar_metadata_step').show();
                    $('#action_btn_part').show();
                    $('#dataset_transfer_next_btn').show().attr('step', 'radar-section');
                    $('#dataset_transfer_back_btn').show();
                    $('#dataset_transfer_submit').hide().data('publishing', false).prop('disabled', false);
                    show_radar_validation_errors(data.errors);
                    return;
                }
                show_publish_failure(
                    data && data.error ? data.error : "HTTP " + req.status,
                    data && data.message ? data.message : get_publish_error_message(req),
                    data && data.existing_transfer ? data.existing_transfer : null
                );
            }
        };
        req.onerror = function() {
            console.error("Dataset transfer publish request failed", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            if (req.status && req.responseText) {
                let data = parse_publish_response(req.responseText);
                show_publish_failure(
                    data && data.error ? data.error : "HTTP " + req.status,
                    data && data.message ? data.message : get_publish_error_message(req)
                );
            }
            else {
                show_publish_failure(
                    "Network error",
                    "The publish request could not reach the server. Please check the CKAN server logs for dataset_transfer/RADAR entries."
                );
            }
        };
        req.ontimeout = function() {
            console.error("Dataset transfer publish request timed out", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            show_publish_failure("Timeout", "Publishing took too long and the browser stopped waiting. Please check the dataset page before trying again.");
        };
        req.onabort = function() {
            console.error("Dataset transfer publish request aborted", {
                url: dest_url,
                status: req.status,
                responseText: req.responseText
            });
            show_publish_failure("Aborted", "The publish request was aborted.");
        };
        req.open("POST", dest_url);
        req.send(formdata);
    });


    /**
     * Check the "use existing token checkbox"
     */
    $('input[name="api_token_choice"]').change(function(){
        $('#api_token_input_empty_alert_box').hide();
        if($(this).val() === 'saved'){
            $('#token_exist_box').val('true');
            $('#new_api_token_controls').prop('hidden', true);
            $('#transfer_api_token_input').val('');
            $('#save_api_token_box').prop('checked', false);
        }
        else{
            $('#token_exist_box').val('false');
            $('#new_api_token_controls').prop('hidden', false);
            $('#transfer_api_token_input').trigger('focus');
        }
    });


    /**
     * Hide the alert when api token input changes
     */
     $('#transfer_api_token_input').keydown(function(){
        $('#api_token_input_empty_alert_box').hide();
        $('#api_token_not_exist_alert_box').hide();
     });


     $('#dataset_transfer_org_list').click(function(){
        $('#organization_empty_box_alert').hide();
     });

     $('.consent-box').click(function(){
        $('#no_consent_alert_message').hide();
     });

     $('#publish_target').change(function(){
        update_publish_target_fields();
     });

     $(document).on('click', '.radar-add', function(){
        add_radar_row($(this).closest('.radar-repeatable'), $(this).data('template'));
     });
     $(document).on('click', '.radar-remove', function(){
        let row = $(this).closest('.radar-row');
        let publisherChanged = row.hasClass('radar-publisher-row');
        row.remove();
        if(publisherChanged){ sync_rights_holder_from_publisher(); }
        mark_active_radar_section_unreviewed();
     });
     $(document).on('change', '.radar-publisher-scheme', function(){
        let row = $(this).closest('.radar-publisher-row');
        update_publisher_scheme(row);
        validate_organization_identifier(row, 'publisher', true);
     });
     $(document).on('change', '.radar-rights-holder-scheme', function(){
        let row = $(this).closest('.radar-rights-holder-row');
        update_rights_holder_scheme(row);
        validate_organization_identifier(row, 'rights-holder', true);
     });
     $('.radar-publisher-row').each(function(){ update_publisher_scheme($(this)); });
     $('.radar-rights-holder-row').each(function(){ update_rights_holder_scheme($(this)); });
     initialize_person_name_behaviour($('#publish_radar_metadata_step'));

     $(document).on('click', '.radar-section-link', function(){
        let targetIndex = radarSectionOrder.indexOf($(this).data('radar-section-target'));
        if(targetIndex < 0 || targetIndex === radarActiveSection){ return; }
        if(targetIndex > radarActiveSection){
            let errors = errors_for_radar_section(
                validate_radar_metadata_in_browser(collect_radar_metadata()),
                radarSectionOrder[radarActiveSection]
            );
            if(errors.length){
                set_radar_section_status(radarSectionOrder[radarActiveSection], 'attention');
                show_radar_validation_errors(errors);
                return;
            }
            radarReviewedSections[radarSectionOrder[radarActiveSection]] = true;
            set_radar_section_status(radarSectionOrder[radarActiveSection], 'complete');
        }
        show_radar_section(targetIndex, true);
     });

     $(document).on('input change', '#publish_radar_metadata_step input, #publish_radar_metadata_step textarea, #publish_radar_metadata_step select', function(){
        if(!$(this).is('#radar_rights_same_as_publisher')){
            mark_active_radar_section_unreviewed();
        }
     });

     $(document).on('input', '.radar-given-name, .radar-family-name', function(){
        derive_person_name($(this).closest('.radar-person-row'));
     });
     $(document).on('input', '.radar-name', function(){
        $(this).closest('.radar-person-row').data('radar-name-derived', false);
     });
     $(document).on('change', '.radar-creator-type', function(){
        update_person_type($(this).closest('.radar-person-row'));
     });
     $(document).on('input', '.radar-publisher-identifier', function(){
        detect_identifier_scheme($(this).closest('.radar-publisher-row'), 'publisher');
        sync_rights_holder_from_publisher();
     });
     $(document).on('input change', '.radar-publisher-name, .radar-publisher-scheme', sync_rights_holder_from_publisher);
     $(document).on('input', '.radar-rights-holder-identifier', function(){
        detect_identifier_scheme($(this).closest('.radar-rights-holder-row'), 'rights-holder');
     });
     $(document).on('input', '.radar-orcid, .radar-affiliation-ror, .radar-publisher-identifier, .radar-rights-holder-identifier', function(){
        schedule_identifier_validation($(this));
     });
     $(document).on('blur', '.radar-orcid, .radar-affiliation-ror, .radar-publisher-identifier, .radar-rights-holder-identifier', function(){
        validate_identifier_after_blur($(this));
     });
     $(document).on('input', '.radar-organization-search', function(){
        schedule_ror_organization_search($(this));
     });
     $(document).on('keydown', '.radar-organization-search', function(event){
        handle_ror_search_keyboard($(this), event);
     });
     $(document).on('click', '.radar-ror-suggestion', function(){
        select_ror_organization($(this).closest('.radar-ror-search-results').data('radar-input'), $(this).data('radar-organization'));
     });
     $(document).on('click', function(event){
        if(!$(event.target).closest('.radar-ror-search-group').length){
            close_all_ror_search_results();
        }
     });
     $('#radar_rights_same_as_publisher').change(toggle_rights_holder_same_as_publisher);

     if($.fn.select2 && $('#radar_language').length){
        $('#radar_language').select2({
            width: '100%',
            placeholder: $('#radar_language').data('placeholder'),
            allowClear: true
        });
     }

});

function update_publish_target_fields(){
    $('#publish_destination_selection').show();
    $('#publish_radar_metadata_step, #publish_step2, #publish_step3').hide();
    $('#publish_step1').show();
    $('#dataset_transfer_next_btn').show().attr('step', '2');
    $('#dataset_transfer_submit, #dataset_transfer_back_btn').hide();
    let target = $('#publish_target').val();
    let description = $('#publish_target_description');
    if(!target){
        description.text(description.data('initial'));
        $('#publish_target_details').prop('hidden', true);
        $('#action_btn_part').hide();
        return;
    }
    $('#publish_target_details').prop('hidden', false);
    $('#action_btn_part').show();
    $('#dataset_transfer_next_btn').prop('disabled', false);
    if(target === "radar"){
        description.text(description.data('radar'));
        $('.luh-only').hide();
        $('.radar-only').show();
        $('#api_token_input_empty_alert_box').hide();
        $('#dataset_transfer_next_btn').text('Continue');
        if($('#publish_destination_selection').data('radar-transferred') === true){
            $('#dataset_transfer_next_btn').prop('disabled', true).text('Publish');
        }
    }
    else{
        description.text(description.data('luh'));
        $('.luh-only').show();
        $('.radar-only').hide();
        $('#dataset_transfer_next_btn').text('Publish');
    }
}

function initialize_radar_review(){
    let review = $('#publish_radar_metadata_step');
    if(review.data('radar-review-initialized')){ return; }
    review.data('radar-review-initialized', true);
    radarActiveSection = 0;
    initialize_person_name_behaviour(review);
    review.find('.radar-publisher-row').each(function(){
        detect_identifier_scheme($(this), 'publisher');
    });
    review.find('.radar-rights-holder-row').each(function(){
        detect_identifier_scheme($(this), 'rights-holder');
    });
    initialize_identifier_validation(review);
    show_radar_section(0, false);
}

function show_radar_section(index, moveFocus){
    index = Math.max(0, Math.min(index, radarSectionOrder.length - 1));
    radarActiveSection = index;
    let key = radarSectionOrder[index];
    $('.radar-review-section').prop('hidden', true).attr('aria-hidden', 'true');
    let section = $('.radar-review-section[data-radar-section="' + key + '"]');
    section.prop('hidden', false).attr('aria-hidden', 'false');
    $('.radar-section-link').removeClass('is-active').attr('aria-selected', 'false');
    $('.radar-section-link[data-radar-section-target="' + key + '"]')
        .addClass('is-active').attr('aria-selected', 'true');
    $('#dataset_transfer_next_btn')
        .attr('step', 'radar-section')
        .text(index === radarSectionOrder.length - 1 ? 'Continue to Consent' : 'Continue');
    $('#dataset_transfer_back_btn').show();
    if(moveFocus){
        section.attr('tabindex', '-1').trigger('focus');
        $('html, body').animate({scrollTop: $('#publish_radar_metadata_step').offset().top}, 150);
    }
}

function radar_section_for_field(field){
    let base = (field || '').split('.')[0];
    let sections = {
        title: 'dataset', descriptions: 'dataset', production_year: 'dataset',
        resource_type: 'dataset', resource: 'dataset', version: 'dataset',
        additional_titles: 'dataset', creators: 'creators',
        contributors: 'creators', subject_areas: 'classification',
        keywords: 'classification', language: 'classification',
        publishers: 'rights', rights: 'rights', additional_rights: 'rights',
        rights_holders: 'rights', funding_references: 'funding',
        alternate_identifiers: 'funding', related_identifiers: 'funding',
        data_sources: 'funding', software: 'funding', data_processing: 'funding',
        related_information: 'funding'
    };
    return sections[base] || 'dataset';
}

function errors_for_radar_section(errors, section){
    return $.grep(errors || [], function(error){
        return radar_section_for_field(error.field) === section;
    });
}

function set_radar_section_status(section, status){
    let link = $('.radar-section-link[data-radar-section-target="' + section + '"]');
    let labels = {complete: 'Complete', attention: 'Needs attention', pending: 'Not reviewed'};
    link.removeClass('is-complete needs-attention')
        .toggleClass('is-complete', status === 'complete')
        .toggleClass('needs-attention', status === 'attention');
    link.find('.radar-section-status').text(labels[status] || labels.pending);
}

function mark_active_radar_section_unreviewed(){
    let section = radarSectionOrder[radarActiveSection];
    radarReviewedSections[section] = false;
    set_radar_section_status(section, 'pending');
}

function initialize_person_name_behaviour(scope){
    scope.find('.radar-person-row').each(function(){
        let row = $(this);
        let name = clean_value(row.find('.radar-name').val());
        row.data('radar-name-derived', !name);
        if(!name){ derive_person_name(row); }
        update_person_type(row);
    });
}

function derive_person_name(row){
    if(row.find('.radar-creator-type').val() !== 'person'){ return; }
    let nameInput = row.find('.radar-name');
    if(clean_value(nameInput.val()) && !row.data('radar-name-derived')){ return; }
    let completeName = [
        clean_value(row.find('.radar-given-name').val()),
        clean_value(row.find('.radar-family-name').val())
    ].filter(Boolean).join(' ');
    nameInput.val(completeName);
    row.data('radar-name-derived', true);
}

function update_person_type(row){
    let isInstitution = row.find('.radar-creator-type').val() === 'institution';
    row.toggleClass('radar-institution-row', isInstitution);
    row.find('.radar-given-name, .radar-family-name').closest('.form-group')
        .toggle(!isInstitution);
    if(!isInstitution){ derive_person_name(row); }
}

function organization_identifier_fields(input){
    let row = input.closest('.radar-row');
    if(input.hasClass('radar-affiliation')){
        return {identifier: row.find('.radar-affiliation-ror').first(), kind: 'affiliation'};
    }
    if(input.hasClass('radar-publisher-name')){
        return {
            identifier: row.find('.radar-publisher-identifier').first(),
            scheme: row.find('.radar-publisher-scheme').first(),
            schemeUri: row.find('.radar-publisher-scheme-uri').first(),
            kind: 'publisher'
        };
    }
    return {
        identifier: row.find('.radar-rights-holder-identifier').first(),
        scheme: row.find('.radar-rights-holder-scheme').first(),
        schemeUri: row.find('.radar-rights-holder-scheme-uri').first(),
        kind: 'rights-holder'
    };
}

function schedule_ror_organization_search(input){
    clearTimeout(input.data('radar-ror-search-timer'));
    let selectedName = clean_value(input.data('radar-selected-ror-name'));
    let selectedId = clean_value(input.data('radar-selected-ror-id'));
    let fields = organization_identifier_fields(input);
    if(selectedName && clean_value(input.val()) !== selectedName){
        if(clean_value(fields.identifier.val()) === selectedId){
            fields.identifier.val('');
            invalidate_identifier_verification(fields.identifier);
            if(fields.scheme){ fields.scheme.val(''); }
            if(fields.schemeUri){ fields.schemeUri.val(''); }
            if(fields.kind === 'publisher'){
                update_publisher_scheme(input.closest('.radar-publisher-row'));
                sync_rights_holder_from_publisher();
            }
            else if(fields.kind === 'rights-holder'){
                update_rights_holder_scheme(input.closest('.radar-rights-holder-row'));
            }
        }
        input.removeData('radar-selected-ror-name radar-selected-ror-id');
    }
    let query = clean_value(input.val());
    radarOrganizationSearchSequence += 1;
    input.data('radar-ror-search-sequence', radarOrganizationSearchSequence);
    if(query.length < 2){
        close_ror_search_results(input);
        return;
    }
    input.data('radar-ror-search-timer', setTimeout(function(){
        search_ror_organizations(input, query, input.data('radar-ror-search-sequence'));
    }, radarOrganizationSearchDelay));
}

function search_ror_organizations(input, query, sequence){
    render_ror_search_message(input, 'Searching the ROR registry…', true);
    let cacheKey = query.toLocaleLowerCase();
    let cached = radarOrganizationSearchCache[cacheKey];
    if(cached){
        render_ror_search_if_current(input, query, sequence, cached);
        return;
    }
    $.ajax({
        url: 'https://api.ror.org/v2/organizations',
        method: 'GET',
        dataType: 'json',
        data: {query: query},
        timeout: radarIdentifierRequestTimeout
    }).then(function(data){
        let results = parse_ror_organization_results(data);
        radarOrganizationSearchCache[cacheKey] = results;
        render_ror_search_if_current(input, query, sequence, results);
    }, function(){
        if(ror_search_is_current(input, query, sequence)){
            render_ror_search_message(input, 'Organization search is temporarily unavailable. You can continue with manual entry.', false);
        }
    });
}

function parse_ror_organization_results(data){
    return $.map((data && data.items) || [], function(item){
        let name = '';
        $.each(item.names || [], function(_, candidate){
            if((candidate.types || []).indexOf('ror_display') !== -1){
                name = candidate.value || '';
                return false;
            }
        });
        if(!name && item.names && item.names.length){ name = item.names[0].value || ''; }
        let normalized = normalize_ror(clean_value(item.id));
        return name && normalized.formatValid && normalized.checksumValid ?
            {name: name, id: normalized.canonical} : null;
    });
}

function ror_search_is_current(input, query, sequence){
    return input.data('radar-ror-search-sequence') === sequence && clean_value(input.val()) === query;
}

function render_ror_search_if_current(input, query, sequence, results){
    if(!ror_search_is_current(input, query, sequence)){ return; }
    if(!results.length){
        render_ror_search_message(input, 'No matching organizations found.', false);
        return;
    }
    let list = ror_search_results(input).empty().attr('role', 'listbox');
    $.each(results.slice(0, 10), function(index, organization){
        $('<button type="button" class="radar-ror-suggestion" role="option"></button>')
            .attr('id', list.attr('id') + '_option_' + index)
            .append($('<strong></strong>').text(organization.name))
            .append($('<small></small>').text(organization.id))
            .data('radar-organization', organization)
            .appendTo(list);
    });
    open_ror_search_results(input, list);
}

function ror_search_results(input){
    let group = input.closest('.radar-ror-search-group');
    let list = group.find('.radar-ror-search-results').first();
    if(!list.length){
        let inputId = input.attr('id') || ('radar_ror_search_' + (++radarDynamicRowId));
        input.attr('id', inputId);
        list = $('<div class="radar-ror-search-results" aria-live="polite"></div>')
            .attr('id', inputId + '_results')
            .data('radar-input', input)
            .appendTo(group);
        input.attr('aria-controls', list.attr('id'));
    }
    return list;
}

function render_ror_search_message(input, message, loading){
    let list = ror_search_results(input).empty().removeAttr('role');
    $('<div class="radar-ror-search-message"></div>').text(message).appendTo(list);
    input.attr('aria-busy', loading ? 'true' : 'false');
    open_ror_search_results(input, list);
}

function open_ror_search_results(input, list){
    close_all_ror_search_results(input);
    list.show();
    input.attr('aria-expanded', 'true');
}

function close_ror_search_results(input){
    input.closest('.radar-ror-search-group').find('.radar-ror-search-results').hide();
    input.attr('aria-expanded', 'false').removeAttr('aria-activedescendant aria-busy');
}

function close_all_ror_search_results(exceptInput){
    $('.radar-organization-search').each(function(){
        if(!exceptInput || this !== exceptInput[0]){ close_ror_search_results($(this)); }
    });
}

function handle_ror_search_keyboard(input, event){
    let list = input.closest('.radar-ror-search-group').find('.radar-ror-search-results:visible');
    if(!list.length){ return; }
    let options = list.find('.radar-ror-suggestion');
    if(event.key === 'Escape'){
        close_ror_search_results(input);
        return;
    }
    if(!options.length || ['ArrowDown', 'ArrowUp', 'Enter'].indexOf(event.key) === -1){ return; }
    event.preventDefault();
    let active = options.filter('.is-active');
    let index = active.length ? options.index(active) : -1;
    if(event.key === 'Enter'){
        if(active.length){ select_ror_organization(input, active.data('radar-organization')); }
        return;
    }
    index += event.key === 'ArrowDown' ? 1 : -1;
    if(index < 0){ index = options.length - 1; }
    if(index >= options.length){ index = 0; }
    options.removeClass('is-active').attr('aria-selected', 'false');
    active = options.eq(index).addClass('is-active').attr('aria-selected', 'true');
    input.attr('aria-activedescendant', active.attr('id'));
}

function select_ror_organization(input, organization){
    if(!input || !organization){ return; }
    let fields = organization_identifier_fields(input);
    clearTimeout(input.data('radar-ror-search-timer'));
    radarOrganizationSearchSequence += 1;
    input.data('radar-ror-search-sequence', radarOrganizationSearchSequence);
    input.val(organization.name)
        .data('radar-selected-ror-name', organization.name)
        .data('radar-selected-ror-id', organization.id);
    fields.identifier.val(organization.id);
    if(fields.scheme){ fields.scheme.val('ROR'); }
    if(fields.schemeUri){ fields.schemeUri.val('https://ror.org/'); }
    close_ror_search_results(input);
    validate_identifier_input(fields.identifier, true);
    if(fields.kind === 'publisher'){
        update_publisher_scheme(input.closest('.radar-publisher-row'));
        sync_rights_holder_from_publisher();
    }
    else if(fields.kind === 'rights-holder'){
        update_rights_holder_scheme(input.closest('.radar-rights-holder-row'));
    }
    mark_active_radar_section_unreviewed();
}

function detect_identifier_scheme(row, kind){
    let identifier = clean_value(row.find(
        kind === 'publisher' ? '.radar-publisher-identifier' : '.radar-rights-holder-identifier'
    ).val());
    let scheme = row.find(
        kind === 'publisher' ? '.radar-publisher-scheme' : '.radar-rights-holder-scheme'
    );
    if(normalize_ror(identifier).formatValid){
        scheme.val('ROR');
    }
    else if(normalize_orcid(identifier).formatValid){
        scheme.val('ORCID');
    }
    else if(!identifier){
        scheme.val('');
    }
    if(kind === 'publisher'){ update_publisher_scheme(row); }
    else{ update_rights_holder_scheme(row); }
}

function toggle_rights_holder_same_as_publisher(){
    let checkbox = $('#radar_rights_same_as_publisher');
    let rows = $('[data-radar-list="rights_holders"] .radar-rows').first();
    let publishers = $('[data-radar-list="publishers"] .radar-publisher-row');
    let message = $('#radar_same_publisher_message');
    if(checkbox.prop('checked')){
        if(publishers.length !== 1){
            checkbox.prop('checked', false);
            toggle_rights_holder_same_as_publisher();
            message.text('Select this option only when exactly one publisher is present.');
            return;
        }
        rows.data('independent-rights-rows', rows.children().detach());
        add_radar_row($('[data-radar-list="rights_holders"]'), 'rights-holder');
        rows.children().last().addClass('radar-synced-rights-holder');
        sync_rights_holder_from_publisher();
        rows.find('input, select, button.radar-remove').prop('disabled', true);
        message.text('The rights holder follows the current publisher. Clear the checkbox to restore the previous rights holders.');
    }
    else{
        rows.find('.radar-synced-rights-holder').remove();
        let previousRows = rows.data('independent-rights-rows');
        if(previousRows && previousRows.length){ rows.append(previousRows); }
        rows.removeData('independent-rights-rows');
        message.empty();
    }
    mark_active_radar_section_unreviewed();
}

function sync_rights_holder_from_publisher(){
    if(!$('#radar_rights_same_as_publisher').prop('checked')){ return; }
    let publishers = $('[data-radar-list="publishers"] .radar-publisher-row');
    if(publishers.length !== 1){
        toggle_rights_holder_same_as_publisher();
        return;
    }
    let publisher = publishers.first();
    let holder = $('.radar-synced-rights-holder').first();
    holder.find('.radar-rights-holder-name').val(publisher.find('.radar-publisher-name').val());
    holder.find('.radar-rights-holder-identifier').val(publisher.find('.radar-publisher-identifier').val());
    holder.find('.radar-rights-holder-scheme').val(publisher.find('.radar-publisher-scheme').val());
    holder.find('.radar-rights-holder-scheme-uri').val(publisher.find('.radar-publisher-scheme-uri').val());
    validate_organization_identifier(holder, 'rights-holder', true);
}

function initialize_identifier_validation(scope){
    scope.find('.radar-orcid, .radar-affiliation-ror').each(function(){
        if(clean_value($(this).val())){ validate_identifier_input($(this), true); }
    });
    scope.find('.radar-publisher-row').each(function(){
        validate_organization_identifier($(this), 'publisher', true);
    });
    scope.find('.radar-rights-holder-row').each(function(){
        validate_organization_identifier($(this), 'rights-holder', true);
    });
}

function schedule_identifier_validation(input){
    clearTimeout(input.data('radar-identifier-timer'));
    invalidate_identifier_verification(input);
    if(!clean_value(input.val())){ return; }
    input.data('radar-identifier-timer', setTimeout(function(){
        validate_identifier_input(input, true);
    }, radarIdentifierDebounceDelay));
}

function validate_identifier_after_blur(input){
    clearTimeout(input.data('radar-identifier-timer'));
    validate_identifier_input(input, true);
}

function validate_organization_identifier(row, kind, verifyOnline){
    let input = row.find(kind === 'publisher' ? '.radar-publisher-identifier' : '.radar-rights-holder-identifier');
    let scheme = row.find(kind === 'publisher' ? '.radar-publisher-scheme' : '.radar-rights-holder-scheme').val();
    if(scheme === 'ROR'){
        validate_identifier_input(input, verifyOnline);
    }
    else{
        invalidate_identifier_verification(input);
    }
}

function identifier_kind(input){
    if(input.hasClass('radar-orcid')){ return 'orcid'; }
    if(input.hasClass('radar-affiliation-ror')){ return 'ror'; }
    if(input.hasClass('radar-publisher-identifier')){
        return input.closest('.radar-publisher-row').find('.radar-publisher-scheme').val() === 'ROR' ? 'ror' : '';
    }
    if(input.hasClass('radar-rights-holder-identifier')){
        return input.closest('.radar-rights-holder-row').find('.radar-rights-holder-scheme').val() === 'ROR' ? 'ror' : '';
    }
    return '';
}

function invalidate_identifier_verification(input){
    radarIdentifierVerificationSequence += 1;
    input.data('radar-identifier-sequence', radarIdentifierVerificationSequence);
    render_identifier_feedback(input, '', '');
}

function validate_identifier_input(input, verifyOnline){
    let kind = identifier_kind(input);
    let value = clean_value(input.val());
    invalidate_identifier_verification(input);
    let sequence = input.data('radar-identifier-sequence');
    if(!kind || !value){ return; }

    let local = kind === 'orcid' ? normalize_orcid(value) : normalize_ror(value);
    if(!local.formatValid){
        render_identifier_feedback(input, 'invalid', kind === 'orcid' ?
            'Please enter a valid ORCID identifier.' : 'Please enter a valid ROR identifier.');
        return;
    }
    if(!local.checksumValid){
        render_identifier_feedback(input, 'invalid', kind === 'orcid' ?
            'This ORCID identifier has an invalid checksum.' : 'This ROR identifier has invalid check characters.');
        return;
    }

    input.val(local.canonical);
    if(input.hasClass('radar-publisher-identifier')){ sync_rights_holder_from_publisher(); }
    if(!verifyOnline){
        render_identifier_feedback(input, 'valid', identifier_valid_but_unverified_message(kind));
        return;
    }

    let cached = radarIdentifierVerificationCache[kind][local.id];
    if(cached){
        render_registry_result(input, kind, cached);
        return;
    }

    render_identifier_feedback(input, 'checking', kind === 'orcid' ?
        'Checking the ORCID registry…' : 'Checking the ROR registry…');
    verify_identifier_with_cache(kind, local.id).then(function(result){
        let currentKind = identifier_kind(input);
        let current = currentKind === 'orcid' ? normalize_orcid(input.val()) : normalize_ror(input.val());
        if(!identifier_verification_is_current(
            sequence, kind, local.id,
            input.data('radar-identifier-sequence'), currentKind, current.id
        )){
            return;
        }
        render_registry_result(input, kind, result);
    });
}

function identifier_verification_is_current(expectedSequence, expectedKind, expectedId, currentSequence, currentKind, currentId){
    return expectedSequence === currentSequence && expectedKind === currentKind && expectedId === currentId;
}

function normalize_orcid(value){
    let raw = clean_value(value);
    let id = raw.replace(/^https?:\/\/orcid\.org\//i, '').toUpperCase();
    let formatValid = /^\d{4}-\d{4}-\d{4}-[\dX]{4}$/.test(id);
    if(!formatValid){ return {formatValid: false, checksumValid: false, id: id, canonical: raw}; }
    let compact = id.replace(/-/g, '');
    let total = 0;
    for(let index = 0; index < 15; index += 1){
        total = (total + parseInt(compact.charAt(index), 10)) * 2;
    }
    let remainder = (12 - (total % 11)) % 11;
    let expected = remainder === 10 ? 'X' : String(remainder);
    return {
        formatValid: true,
        checksumValid: compact.charAt(15) === expected,
        id: id,
        canonical: 'https://orcid.org/' + id
    };
}

function normalize_ror(value){
    let raw = clean_value(value);
    let id = raw.replace(/^https:\/\/ror\.org\//i, '').replace(/^ror\.org\//i, '').toLowerCase();
    let formatValid = /^0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$/.test(id);
    if(!formatValid){ return {formatValid: false, checksumValid: false, id: id, canonical: raw}; }
    let alphabet = '0123456789abcdefghjkmnpqrstvwxyz';
    let numericValue = 0;
    for(let index = 1; index < 7; index += 1){
        numericValue = (numericValue * 32) + alphabet.indexOf(id.charAt(index));
    }
    let expected = String(98 - ((numericValue * 100) % 97));
    if(expected.length < 2){ expected = '0' + expected; }
    return {
        formatValid: true,
        checksumValid: id.slice(-2) === expected,
        id: id,
        canonical: 'https://ror.org/' + id
    };
}

function verify_identifier_in_registry(kind, id){
    let url = kind === 'orcid' ?
        'https://pub.orcid.org/v3.0/' + encodeURIComponent(id) + '/record' :
        'https://api.ror.org/v2/organizations/' + encodeURIComponent(id);
    return $.ajax({
        url: url,
        method: 'GET',
        dataType: 'json',
        timeout: radarIdentifierRequestTimeout,
        beforeSend: function(request){
            if(kind === 'orcid'){
                request.setRequestHeader('Accept', 'application/vnd.orcid+json');
            }
        }
    }).then(function(data){
        let name = '';
        if(kind === 'ror'){
            $.each(data.names || [], function(_, item){
                if((item.types || []).indexOf('ror_display') !== -1){ name = item.value || ''; return false; }
            });
        }
        return {status: 'verified', name: name};
    }, function(request, textStatus){
        if(request.status === 404){ return {status: 'not_found'}; }
        if(request.status === 429 || request.status === 503){ return {status: 'rate_limited'}; }
        return {status: textStatus === 'timeout' ? 'timeout' : 'unavailable'};
    });
}

function verify_identifier_with_cache(kind, id){
    if(radarIdentifierVerificationRequests[kind][id]){
        return radarIdentifierVerificationRequests[kind][id];
    }
    let request = verify_identifier_in_registry(kind, id).then(function(result){
        delete radarIdentifierVerificationRequests[kind][id];
        if(result.status === 'verified' || result.status === 'not_found'){
            radarIdentifierVerificationCache[kind][id] = result;
        }
        return result;
    });
    radarIdentifierVerificationRequests[kind][id] = request;
    return request;
}

function render_registry_result(input, kind, result){
    if(result.status === 'verified'){
        let message = kind === 'orcid' ? '✓ ORCID verified' : '✓ ROR verified';
        if(kind === 'ror' && result.name){ message += ' — ' + result.name; }
        render_identifier_feedback(input, 'verified', message);
    }
    else if(result.status === 'not_found'){
        render_identifier_feedback(input, 'warning', kind === 'orcid' ?
            'This ORCID identifier could not be found in the ORCID registry.' :
            'This ROR identifier could not be found in the ROR registry.');
    }
    else if(result.status === 'rate_limited'){
        render_identifier_feedback(input, 'warning', (kind === 'orcid' ? 'ORCID' : 'ROR') +
            ' format is valid. Online verification is temporarily rate limited.');
    }
    else{
        render_identifier_feedback(input, 'warning', identifier_valid_but_unverified_message(kind));
    }
}

function identifier_valid_but_unverified_message(kind){
    return (kind === 'orcid' ? 'ORCID' : 'ROR') +
        ' format is valid. Online verification is currently unavailable.';
}

function render_identifier_feedback(input, state, message){
    let group = input.closest('.form-group');
    let feedback = group.find('.radar-identifier-feedback').first();
    if(!feedback.length){
        feedback = $('<span class="help-block radar-identifier-feedback" aria-live="polite"></span>');
        input.after(feedback);
    }
    group.removeClass('radar-identifier-invalid radar-identifier-verified radar-identifier-warning radar-identifier-checking');
    input.removeAttr('aria-busy aria-invalid');
    if(!state || !message){ feedback.empty().hide(); return; }
    group.addClass('radar-identifier-' + state);
    if(state === 'invalid'){ input.attr('aria-invalid', 'true'); }
    if(state === 'checking'){ input.attr('aria-busy', 'true'); }
    feedback.text(message).show();
}

function clean_value(value){
    return $.trim(value || '');
}

function collect_radar_metadata(){
    let metadata = {
        title: clean_value($('#radar_title').val()),
        descriptions: [], creators: [], contributors: [], additional_titles: [],
        publishers: [], production_year: clean_value($('#radar_production_year').val()),
        publication_year: '', subject_areas: [], resource_type: $('#radar_resource_type').val(),
        resource: clean_value($('#radar_resource').val()), rights: $('#radar_rights').val(),
        additional_rights: clean_value($('#radar_additional_rights').val()),
        rights_holders: [], keywords: [], language: $('#radar_language').val(),
        version: clean_value($('#radar_version').val()), alternate_identifiers: [], related_identifiers: [],
        data_sources: [], software: [], data_processing: [], related_information: [], funding_references: []
    };
    let description = clean_value($('#radar_description').val());
    if(description){ metadata.descriptions.push({value: description, type: 'Abstract'}); }
    $('[data-radar-list="descriptions"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ metadata.descriptions.push({value: value, type: $(this).find('.radar-type').val()}); } });
    $('[data-radar-list="creators"] .radar-person-row').each(function(){ metadata.creators.push(collect_person($(this))); });
    $('[data-radar-list="contributors"] .radar-person-row').each(function(){ let item = collect_person($(this)); item.type = $(this).find('.radar-contributor-type').val(); metadata.contributors.push(item); });
    $('[data-radar-list="publishers"] .radar-publisher-row').each(function(){ let row = $(this); metadata.publishers.push({name: clean_value(row.find('.radar-publisher-name').val()), name_identifier: clean_value(row.find('.radar-publisher-identifier').val()), name_identifier_scheme: row.find('.radar-publisher-scheme').val(), scheme_uri: clean_value(row.find('.radar-publisher-scheme-uri').val())}); });
    $('[data-radar-list="rights_holders"] .radar-rights-holder-row').each(function(){ let row = $(this); metadata.rights_holders.push({name: clean_value(row.find('.radar-rights-holder-name').val()), name_identifier: clean_value(row.find('.radar-rights-holder-identifier').val()), name_identifier_scheme: row.find('.radar-rights-holder-scheme').val(), scheme_uri: clean_value(row.find('.radar-rights-holder-scheme-uri').val())}); });
    $('[data-radar-list="subject_areas"] .radar-row').each(function(){ metadata.subject_areas.push({controlled: $(this).find('.radar-subject-controlled').val(), additional: clean_value($(this).find('.radar-subject-additional').val())}); });
    $('[data-radar-list="keywords"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ metadata.keywords.push({value: value, scheme: $(this).find('.radar-keyword-scheme').val(), scheme_uri: clean_value($(this).find('.radar-scheme-uri').val()), value_uri: clean_value($(this).find('.radar-value-uri').val()), classification_code: clean_value($(this).find('.radar-classification-code').val()), ontology_uri: clean_value($(this).find('.radar-ontology-uri').val()), ontology_id: clean_value($(this).find('.radar-ontology-id').val())}); }});
    collect_object_rows('additional_titles', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: row.find('.radar-type').val()}; }, metadata);
    collect_object_rows('alternate_identifiers', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: clean_value(row.find('.radar-type').val())}; }, metadata);
    collect_object_rows('related_identifiers', function(row){ return {value: clean_value(row.find('.radar-value').val()), identifier_type: row.find('.radar-identifier-type').val(), relation_type: row.find('.radar-relation-type').val()}; }, metadata);
    collect_object_rows('data_sources', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: row.find('.radar-type').val()}; }, metadata);
    collect_object_rows('software', function(row){ return {name: clean_value(row.find('.radar-name').val()), version: clean_value(row.find('.radar-version').val()), type: row.find('.radar-type').val(), alternative_name: clean_value(row.find('.radar-alternative-name').val()), alternative_version: clean_value(row.find('.radar-alternative-version').val())}; }, metadata, 'name');
    collect_object_rows('related_information', function(row){ return {value: clean_value(row.find('.radar-value').val()), type: clean_value(row.find('.radar-type').val())}; }, metadata);
    collect_object_rows('funding_references', function(row){ return {funder_name: clean_value(row.find('.radar-funder-name').val()), funder_identifier: clean_value(row.find('.radar-funder-identifier').val()), funder_identifier_type: row.find('.radar-funder-type').val(), funder_scheme_uri: clean_value(row.find('.radar-scheme-uri').val()), award_number: clean_value(row.find('.radar-award-number').val()), award_uri: clean_value(row.find('.radar-award-uri').val()), award_title: clean_value(row.find('.radar-award-title').val())}; }, metadata, 'funder_name');
    metadata.data_processing = collect_text_rows('data_processing');
    return metadata;
}

function collect_person(row){
    let reviewConfirmation = row.find('.radar-review-confirmation');
    return {creator_type: row.find('.radar-creator-type').val() || '', name: clean_value(row.find('.radar-name').val()), given_name: clean_value(row.find('.radar-given-name').val()), family_name: clean_value(row.find('.radar-family-name').val()), orcid: clean_value(row.find('.radar-orcid').val()), affiliation: clean_value(row.find('.radar-affiliation').val()), affiliation_ror: clean_value(row.find('.radar-affiliation-ror').val()), source_name: clean_value(row.find('.radar-source-name').val()), needs_review: reviewConfirmation.length ? !reviewConfirmation.prop('checked') : false};
}

function collect_text_rows(name){
    let values = [];
    $('[data-radar-list="' + name + '"] .radar-row').each(function(){ let value = clean_value($(this).find('.radar-value').val()); if(value){ values.push(value); } });
    return values;
}

function collect_object_rows(name, builder, metadata, key){
    $('[data-radar-list="' + name + '"] .radar-row').each(function(){ let item = builder($(this)); if(clean_value(item[key || 'value'])){ metadata[name].push(item); } });
}

function validate_radar_metadata_in_browser(metadata){
    let errors = [];
    if(!metadata.title){ errors.push({field: 'title', message: 'Please provide a title.'}); }
    if(!metadata.creators.length){ errors.push({field: 'creators', message: 'Please add at least one creator.'}); }
    $.each(metadata.creators, function(index, creator){
        let personName = creator.name || creator.given_name || creator.family_name;
        if(['person', 'institution'].indexOf(creator.creator_type) === -1){ errors.push({field: 'creators.' + index + '.creator_type', message: 'Please select whether the creator is a person or institution.'}); }
        if(!personName){ errors.push({field: 'creators.' + index + '.name', message: 'Please provide the creator name.'}); }
        if(creator.needs_review){ errors.push({field: 'creators.' + index + '.needs_review', message: 'Please verify the automatically extracted given and family names.'}); }
        if(creator.orcid && !valid_orcid_format(creator.orcid)){ errors.push({field: 'creators.' + index + '.orcid', message: 'Please provide a valid ORCID.'}); }
        if(creator.affiliation_ror && !valid_ror_format(creator.affiliation_ror)){ errors.push({field: 'creators.' + index + '.affiliation_ror', message: 'Please provide a valid ROR identifier.'}); }
        if(creator.affiliation_ror && !creator.affiliation){ errors.push({field: 'creators.' + index + '.affiliation', message: 'Provide an affiliation name when a ROR identifier is supplied.'}); }
    });
    $.each(metadata.contributors, function(index, contributor){
        let personName = contributor.name || contributor.given_name || contributor.family_name;
        if(['person', 'institution'].indexOf(contributor.creator_type) === -1){ errors.push({field: 'contributors.' + index + '.creator_type', message: 'Please select whether the contributor is a person or institution.'}); }
        if(!personName){ errors.push({field: 'contributors.' + index + '.name', message: 'Please provide the contributor name.'}); }
        if(contributor.needs_review){ errors.push({field: 'contributors.' + index + '.needs_review', message: 'Please verify the automatically extracted given and family names.'}); }
        if(contributor.orcid && !valid_orcid_format(contributor.orcid)){ errors.push({field: 'contributors.' + index + '.orcid', message: 'Please provide a valid ORCID.'}); }
        if(contributor.affiliation_ror && !valid_ror_format(contributor.affiliation_ror)){ errors.push({field: 'contributors.' + index + '.affiliation_ror', message: 'Please provide a valid ROR identifier.'}); }
        if(contributor.affiliation_ror && !contributor.affiliation){ errors.push({field: 'contributors.' + index + '.affiliation', message: 'Provide an affiliation name when a ROR identifier is supplied.'}); }
    });
    if(!metadata.production_year){ errors.push({field: 'production_year', message: 'Please provide the production year.'}); }
    if(!metadata.subject_areas.length){ errors.push({field: 'subject_areas', message: 'Please select a scientific subject area.'}); }
    let subjectAreas = {};
    $.each(metadata.subject_areas, function(index, area){
        let key = (area.controlled + '|' + area.additional).toLowerCase();
        if(subjectAreas[key]){ errors.push({field: 'subject_areas.' + index, message: 'Please remove duplicate subject areas.'}); }
        subjectAreas[key] = true;
    });
    if(!subjectAreas['engineering|']){ errors.push({field: 'subject_areas', message: 'Engineering is required as a subject area.'}); }
    if(metadata.resource_type !== 'Dataset'){ errors.push({field: 'resource_type', message: 'RADAR resource type must be Dataset.'}); }
    if(!metadata.publishers.length || !metadata.publishers[0].name){ errors.push({field: 'publishers', message: 'Please provide a publisher.'}); }
    $.each(metadata.publishers, function(index, publisher){
        if(publisher.name_identifier_scheme === 'ROR' && publisher.name_identifier && !valid_ror_format(publisher.name_identifier)){ errors.push({field: 'publishers.' + index + '.name_identifier', message: 'Please provide a valid publisher ROR identifier.'}); }
        if(publisher.name_identifier_scheme === 'ORCID' && publisher.name_identifier && !valid_orcid_format(publisher.name_identifier)){ errors.push({field: 'publishers.' + index + '.name_identifier', message: 'Please provide a valid publisher ORCID.'}); }
    });
    if(!metadata.rights){ errors.push({field: 'rights', message: 'Please select a licence.'}); }
    else if(radarSupportedRights.indexOf(metadata.rights) === -1){ errors.push({field: 'rights', message: 'Please select a valid RADAR licence.'}); }
    if(!metadata.rights_holders.length){ errors.push({field: 'rights_holders', message: 'Please provide a rights holder.'}); }
    $.each(metadata.rights_holders, function(index, holder){
        if(!holder.name){ errors.push({field: 'rights_holders.' + index + '.name', message: 'Please provide the rights holder name.'}); }
        if(holder.name_identifier_scheme === 'ROR' && holder.name_identifier && !valid_ror_format(holder.name_identifier)){ errors.push({field: 'rights_holders.' + index + '.name_identifier', message: 'Please provide a valid rights holder ROR identifier.'}); }
        if(holder.name_identifier_scheme === 'ORCID' && holder.name_identifier && !valid_orcid_format(holder.name_identifier)){ errors.push({field: 'rights_holders.' + index + '.name_identifier', message: 'Please provide a valid rights holder ORCID.'}); }
    });
    $.each(metadata.related_identifiers, function(index, identifier){
        if(!identifier.relation_type){
            errors.push({field: 'related_identifiers.' + index + '.relation_type', message: 'Please select a relationship for every related identifier.'});
        }
    });
    return errors;
}

function valid_orcid_format(value){
    let result = normalize_orcid(value);
    return result.formatValid && result.checksumValid;
}

function valid_ror_format(value){
    let result = normalize_ror(value);
    return result.formatValid && result.checksumValid;
}

function render_radar_confirmation(metadata){
    let body = $('#radar_confirmation_body').empty();
    append_radar_confirmation_group(body, 'Dataset Information');
    append_radar_confirmation_row(body, 'Identifier', 'Assigned by RADAR after transfer');
    append_radar_confirmation_row(body, 'Title', metadata.title);
    append_radar_confirmation_row(body, 'Additional Titles', format_radar_items(metadata.additional_titles, function(item){ return item.value + ' (' + item.type + ')'; }));
    append_radar_confirmation_row(body, 'Descriptions', format_radar_items(metadata.descriptions, function(item){ return item.type + ': ' + item.value; }));
    append_radar_confirmation_row(body, 'Production Year', metadata.production_year);
    append_radar_confirmation_row(body, 'Publication Year', 'Managed by RADAR');
    append_radar_confirmation_row(body, 'Resource Type', metadata.resource_type);
    append_radar_confirmation_row(body, 'Resource Description', metadata.resource);
    append_radar_confirmation_row(body, 'Version', metadata.version);

    append_radar_confirmation_group(body, 'Creators and Contributors');
    append_radar_confirmation_row(body, 'Creators', format_radar_items(metadata.creators, format_radar_person));
    append_radar_confirmation_row(body, 'Contributors', format_radar_items(metadata.contributors, function(item){
        return format_radar_person(item) + (item.type ? ' | Role: ' + item.type : '');
    }));

    append_radar_confirmation_group(body, 'Classification and Keywords');
    append_radar_confirmation_row(body, 'Subject Areas', format_radar_items(metadata.subject_areas, function(item){ return item.controlled + (item.additional ? ': ' + item.additional : ''); }));
    append_radar_confirmation_row(body, 'Keywords', format_radar_items(metadata.keywords, function(item){
        return format_radar_details(item.value, [
            ['Scheme', item.scheme], ['Scheme URI', item.scheme_uri],
            ['Value URI', item.value_uri], ['Classification Code', item.classification_code],
            ['Ontology URI', item.ontology_uri], ['Ontology ID', item.ontology_id]
        ]);
    }));
    append_radar_confirmation_row(body, 'Language', metadata.language);

    append_radar_confirmation_group(body, 'Rights and Publication');
    append_radar_confirmation_row(body, 'Publishers', format_radar_items(metadata.publishers, format_radar_organization));
    append_radar_confirmation_row(body, 'Licence', metadata.rights);
    append_radar_confirmation_row(body, 'Additional Rights Statement', metadata.additional_rights);
    append_radar_confirmation_row(body, 'Rights Holders', format_radar_items(metadata.rights_holders, format_radar_organization));

    if(metadata.funding_references.length){
        append_radar_confirmation_group(body, 'Funding References');
        append_radar_confirmation_row(body, 'Funding', format_radar_items(metadata.funding_references, function(item){
            return format_radar_details(item.funder_name, [
                ['Funder Identifier', item.funder_identifier], ['Identifier Type', item.funder_identifier_type],
                ['Scheme URI', item.funder_scheme_uri], ['Award Number', item.award_number],
                ['Award URI', item.award_uri], ['Project Title', item.award_title]
            ]);
        }));
    }

    let hasAdditionalMetadata = metadata.alternate_identifiers.length || metadata.related_identifiers.length ||
        metadata.data_sources.length || metadata.software.length || metadata.data_processing.length ||
        metadata.related_information.length;
    if(hasAdditionalMetadata){
        append_radar_confirmation_group(body, 'Additional Research Metadata');
        append_radar_confirmation_row(body, 'Alternate Identifiers', format_radar_items(metadata.alternate_identifiers, function(item){ return item.value + ' (' + item.type + ')'; }));
        append_radar_confirmation_row(body, 'Related Identifiers', format_radar_items(metadata.related_identifiers, function(item){ return format_radar_details(item.value, [['Identifier Type', item.identifier_type], ['Relation Type', item.relation_type]]); }));
        append_radar_confirmation_row(body, 'Data Sources', format_radar_items(metadata.data_sources, function(item){ return item.value + ' (' + item.type + ')'; }));
        append_radar_confirmation_row(body, 'Software Information', format_radar_items(metadata.software, function(item){ return format_radar_details(item.name, [['Version', item.version], ['Purpose', item.type], ['Alternative Name', item.alternative_name], ['Alternative Version', item.alternative_version]]); }));
        append_radar_confirmation_row(body, 'Data Processing', (metadata.data_processing || []).join('\n'));
        append_radar_confirmation_row(body, 'Related Information', format_radar_items(metadata.related_information, function(item){ return format_radar_details(item.value, [['Type', item.type]]); }));
    }
}

function append_radar_confirmation_group(body, title){
    body.append($('<tr class="radar-confirmation-group"></tr>').append($('<th colspan="2"></th>').text(title)));
}

function append_radar_confirmation_row(body, label, value){
    value = clean_value(value);
    if(!value){ return; }
    body.append(
        $('<tr></tr>')
            .append($('<th scope="row"></th>').text(label))
            .append($('<td></td>').text(value))
    );
}

function format_radar_items(items, formatter){
    return $.map(items || [], function(item){
        return clean_value(formatter(item));
    }).filter(Boolean).join('\n');
}

function format_radar_person(item){
    let name = item.name || [item.family_name, item.given_name].filter(Boolean).join(', ');
    let details = [
        ['Given Name', item.given_name], ['Family Name', item.family_name],
        ['ORCID', item.orcid], ['Affiliation', item.affiliation],
        ['Affiliation ROR', item.affiliation_ror]
    ];
    if(item.creator_type){
        details.unshift(['Creator Type', item.creator_type === 'institution' ? 'Institution' : 'Person']);
    }
    return format_radar_details(name, details);
}

function format_radar_organization(item){
    return format_radar_details(item.name, [
        ['Name Identifier', item.name_identifier],
        ['Identifier Scheme', item.name_identifier_scheme],
        ['Scheme URI', item.scheme_uri]
    ]);
}

function format_radar_details(primary, details){
    let values = [];
    if(clean_value(primary)){ values.push(clean_value(primary)); }
    $.each(details, function(_, detail){
        if(clean_value(detail[1])){ values.push(detail[0] + ': ' + clean_value(detail[1])); }
    });
    return values.join(' | ');
}

function clear_radar_validation_errors(){
    $('#radar_validation_summary').hide().empty();
    $('[data-radar-field]').removeClass('has-error').find('.radar-error').remove();
}

function show_radar_validation_errors(errors){
    clear_radar_validation_errors();
    let list = $('<ul></ul>');
    let firstSection = null;
    $.each(errors, function(_, error){
        list.append($('<li></li>').text(error.message));
        let base = (error.field || '').split('.')[0];
        let section = radar_section_for_field(error.field);
        firstSection = firstSection || section;
        set_radar_section_status(section, 'attention');
        let group = $('[data-radar-field="' + base + '"]').first();
        group.addClass('has-error').append($('<span class="help-block radar-error"></span>').text(error.message));
        group.closest('details').prop('open', true);
    });
    if(firstSection){
        show_radar_section(radarSectionOrder.indexOf(firstSection), false);
    }
    $('#radar_validation_summary').append($('<strong></strong>').text('Please correct the following RADAR metadata:')).append(list).show();
    $('html, body').animate({scrollTop: $('#publish_radar_metadata_step').offset().top}, 200);
    $('#radar_validation_summary').trigger('focus');
}

function add_radar_row(container, template){
    radarDynamicRowId += 1;
    let id = 'radar_dynamic_' + radarDynamicRowId;
    let remove = '<div class="col-md-1 radar-remove-column"><button type="button" class="btn btn-default btn-sm radar-remove" aria-label="Remove">&times;</button></div>';
    let keywordRemove = '<div class="col-md-1 radar-remove-column"><button type="button" class="btn btn-default btn-sm radar-remove" aria-label="Remove keyword" title="Remove keyword"><i class="fa fa-trash" aria-hidden="true"></i></button></div>';
    let html = '';
    if(template === 'text'){ html = '<div class="radar-row input-group"><label class="sr-only" for="' + id + '">Value</label><input id="' + id + '" class="form-control radar-value"><span class="input-group-btn"><button type="button" class="btn btn-default radar-remove" aria-label="Remove">&times;</button></span></div>'; }
    else if(template === 'publisher'){
        html = '<div class="radar-row radar-publisher-row"><div class="radar-card-heading"><strong>Publisher</strong><button type="button" class="btn btn-default btn-sm radar-remove">Remove</button></div><div class="row"><div class="col-md-6 form-group radar-ror-search-group"><label for="' + id + '_name">Publisher Name *</label><input id="' + id + '_name" class="form-control radar-publisher-name radar-organization-search" autocomplete="off" aria-autocomplete="list" aria-expanded="false"><span class="help-block">Type at least 2 characters to search the ROR registry, or enter an organization manually.</span></div><div class="col-md-6 form-group"><label for="' + id + '_identifier">Publisher Identifier</label><input id="' + id + '_identifier" class="form-control radar-publisher-identifier" placeholder="https://ror.org/..."></div></div><div class="row radar-identifier-details"><div class="col-md-6 form-group"><label for="' + id + '_scheme">Identifier Scheme</label><select id="' + id + '_scheme" class="form-control radar-publisher-scheme">' + $('#radar-template-publisher-scheme-options').html() + '</select></div></div><input type="hidden" class="radar-publisher-scheme-uri"></div>';
    }
    else if(template === 'rights-holder'){
        html = '<div class="radar-row radar-rights-holder-row"><div class="radar-card-heading"><strong>Rights Holder</strong><button type="button" class="btn btn-default btn-sm radar-remove">Remove</button></div><div class="row"><div class="col-md-6 form-group radar-ror-search-group"><label for="' + id + '_name">Rights Holder Name *</label><input id="' + id + '_name" class="form-control radar-rights-holder-name radar-organization-search" autocomplete="off" aria-autocomplete="list" aria-expanded="false"><span class="help-block">Type at least 2 characters to search the ROR registry, or enter an organization manually.</span></div><div class="col-md-6 form-group"><label for="' + id + '_identifier">Name Identifier</label><input id="' + id + '_identifier" class="form-control radar-rights-holder-identifier" placeholder="https://ror.org/..."></div></div><div class="row radar-identifier-details"><div class="col-md-6 form-group"><label for="' + id + '_scheme">Identifier Scheme</label><select id="' + id + '_scheme" class="form-control radar-rights-holder-scheme">' + $('#radar-template-publisher-scheme-options').html() + '</select></div></div><input type="hidden" class="radar-rights-holder-scheme-uri"></div>';
    }
    else if(template === 'textarea'){ html = '<div class="radar-row"><label class="sr-only" for="' + id + '">Description</label><textarea id="' + id + '" class="form-control radar-value" rows="3"></textarea><button type="button" class="btn btn-default btn-sm radar-remove">Remove</button></div>'; }
    else if(template === 'creator' || template === 'contributor'){
        let label = template === 'contributor' ? 'Contributor' : 'Creator';
        let role = template === 'contributor' ? '<div class="col-md-4 form-group"><label for="' + id + '_role">Role</label><select id="' + id + '_role" class="form-control radar-contributor-type">' + $('#radar-template-options').html() + '</select></div>' : '';
        html = '<div class="radar-row radar-person-row radar-person-card' + (template === 'contributor' ? ' radar-contributor-row' : '') + '"><div class="radar-card-heading"><strong>' + label + '</strong><button type="button" class="btn btn-default btn-sm radar-remove">Remove</button></div><div class="row radar-personal-fields"><div class="col-md-4 form-group"><label for="' + id + '_type">' + label + ' Type</label><select id="' + id + '_type" class="form-control radar-creator-type"><option value="person" selected>Person</option><option value="institution">Institution</option></select></div><div class="col-md-8 form-group"><label for="' + id + '_name">' + label + ' Name' + (template === 'creator' ? ' *' : '') + '</label><input id="' + id + '_name" class="form-control radar-name"></div></div><div class="row"><div class="col-md-6 form-group"><label for="' + id + '_given">Given Name</label><input id="' + id + '_given" class="form-control radar-given-name"></div><div class="col-md-6 form-group"><label for="' + id + '_family">Family Name</label><input id="' + id + '_family" class="form-control radar-family-name"></div></div><div class="row"><div class="col-md-' + (template === 'contributor' ? '8' : '12') + ' form-group"><label for="' + id + '_orcid">ORCID</label><input id="' + id + '_orcid" class="form-control radar-orcid" placeholder="https://orcid.org/0000-0000-0000-0000"></div>' + role + '</div><div class="row radar-affiliation-fields"><div class="col-md-6 form-group radar-ror-search-group"><label for="' + id + '_affiliation">Affiliation</label><input id="' + id + '_affiliation" class="form-control radar-affiliation radar-organization-search" autocomplete="off" aria-autocomplete="list" aria-expanded="false"><span class="help-block">Type at least 2 characters to search the ROR registry, or enter an affiliation manually.</span></div><div class="col-md-6 form-group"><label for="' + id + '_ror">Affiliation ROR</label><input id="' + id + '_ror" class="form-control radar-affiliation-ror" placeholder="https://ror.org/..."></div></div></div>';
    }
    else if(template === 'subject-area'){ html = '<div class="radar-row row"><div class="col-md-5"><select class="form-control radar-subject-controlled">' + $('#radar-template-subject-options').html() + '</select></div><div class="col-md-6"><input class="form-control radar-subject-additional" placeholder="Specify when Other"></div>' + remove + '</div>'; }
    else if(template === 'keyword'){ html = '<div class="radar-row radar-keyword-row"><div class="row"><div class="col-md-11"><label for="' + id + '">Keyword</label><input id="' + id + '" class="form-control radar-value"></div>' + keywordRemove + '</div><input type="hidden" class="radar-keyword-scheme" value="Other"><input type="hidden" class="radar-scheme-uri"><input type="hidden" class="radar-value-uri"><input type="hidden" class="radar-classification-code"><input type="hidden" class="radar-ontology-uri"><input type="hidden" class="radar-ontology-id"></div>'; }
    else if(template === 'additional-title'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Title"></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-additional-title-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'description'){ html = '<div class="radar-row row"><div class="col-md-7"><textarea class="form-control radar-value" rows="2" placeholder="Description"></textarea></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-description-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'alternate-identifier'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Identifier"></div><div class="col-md-4"><input class="form-control radar-type" placeholder="Identifier type"></div>' + remove + '</div>'; }
    else if(template === 'related-identifier'){ html = '<div class="radar-row row"><div class="col-md-4"><input class="form-control radar-value" placeholder="Identifier"></div><div class="col-md-3"><select class="form-control radar-identifier-type">' + $('#radar-template-related-id-options').html() + '</select></div><div class="col-md-4"><select class="form-control radar-relation-type">' + $('#radar-template-relation-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'data-source'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Source description"></div><div class="col-md-4"><select class="form-control radar-type">' + $('#radar-template-data-source-options').html() + '</select></div>' + remove + '</div>'; }
    else if(template === 'software'){ html = '<div class="radar-row row"><div class="col-md-3"><input class="form-control radar-name" placeholder="Software name"></div><div class="col-md-2"><input class="form-control radar-version" placeholder="Version"></div><div class="col-md-3"><select class="form-control radar-type">' + $('#radar-template-software-options').html() + '</select></div><div class="col-md-3"><input class="form-control radar-alternative-name" placeholder="Alternative name"></div>' + remove + '</div>'; }
    else if(template === 'related-information'){ html = '<div class="radar-row row"><div class="col-md-7"><input class="form-control radar-value" placeholder="Information"></div><div class="col-md-4"><input class="form-control radar-type" placeholder="Information type"></div>' + remove + '</div>'; }
    else if(template === 'funding'){ html = '<div class="radar-row radar-funding-row"><div class="radar-card-heading"><strong>Additional Funding Reference</strong><button type="button" class="btn btn-default btn-sm radar-remove">Remove</button></div><div class="row"><div class="col-md-4 form-group"><label>Funder Name</label><input class="form-control radar-funder-name"></div><div class="col-md-4 form-group"><label>Funder Identifier</label><input class="form-control radar-funder-identifier"></div><div class="col-md-4 form-group"><label>Identifier Type</label><select class="form-control radar-funder-type"><option value=""></option>' + $('#radar-template-funder-options').html() + '</select></div></div><div class="form-group"><label>Funder Scheme URI</label><input class="form-control radar-scheme-uri"></div><div class="row"><div class="col-md-4 form-group"><label>Award Number</label><input class="form-control radar-award-number"></div><div class="col-md-4 form-group"><label>Award URI</label><input class="form-control radar-award-uri"></div><div class="col-md-4 form-group"><label>Project Title</label><input class="form-control radar-award-title"></div></div></div>'; }
    let rows = container.find('.radar-rows').first();
    rows.append(html);
    let newRow = rows.children().last();
    initialize_person_name_behaviour(newRow);
    if(template === 'publisher'){
        update_publisher_scheme(newRow);
        if($('#radar_rights_same_as_publisher').prop('checked')){
            $('#radar_rights_same_as_publisher').prop('checked', false);
            toggle_rights_holder_same_as_publisher();
            $('#radar_same_publisher_message').text('The publisher list changed. Confirm the rights holder selection again.');
        }
    }
    else if(template === 'rights-holder'){ update_rights_holder_scheme(newRow); }
    mark_active_radar_section_unreviewed();
}

function update_publisher_scheme(row){
    update_name_identifier_scheme(
        row.find('.radar-publisher-scheme'),
        row.find('.radar-publisher-scheme-uri')
    );
}

function update_rights_holder_scheme(row){
    update_name_identifier_scheme(
        row.find('.radar-rights-holder-scheme'),
        row.find('.radar-rights-holder-scheme-uri')
    );
}

function update_name_identifier_scheme(schemeInput, uri){
    let scheme = schemeInput.val();
    if(scheme === 'ROR'){
        uri.val('https://ror.org/').prop('readonly', true);
    }
    else if(scheme === 'ORCID'){
        uri.val('https://orcid.org/').prop('readonly', true);
    }
    else if(scheme === 'Other'){
        uri.prop('readonly', false);
    }
    else{
        uri.val('').prop('readonly', true);
    }
}

function parse_publish_response(responseText){
    if (responseText === "500") {
        return {"success": false, "error": "Unknown", "message": "None"};
    }
    try {
        return JSON.parse(responseText);
    }
    catch(error) {
        console.error("Dataset transfer publish response was not valid JSON", error, responseText);
        return null;
    }
}

function get_publish_error_message(req){
    if (req.responseText) {
        return req.responseText.substring(0, 1000);
    }
    return "The server did not return a usable response.";
}

function show_publish_success(data){
    console.info("Dataset transfer publish succeeded", data);
    $('#publish_step_final').hide();
    $('#publish_failed_section').hide();
    $('#publish_result_section').show();
    $('#published_doi').text(data['doi'] || '');
    $('#published_url').find('a').attr("href", data['published_url']);
    $('#published_url').find('a').text(data['published_url']);
}

function show_publish_failure(error, message, existingTransfer){
    console.error("Dataset transfer publish failed", error, message);
    $('#publish_step_final').hide();
    $('#publish_result_section').hide();
    $('#publish_failed_section').show();
    $('#published_fail_type').text(error || "Unknown");
    $('#published_fail_message').text(message || "None");
    if(existingTransfer && existingTransfer.published_url){
        $('#published_fail_message').append(' ').append(
            $('<a></a>').attr({href: existingTransfer.published_url, target: '_blank', rel: 'noopener'}).text('View existing transfer')
        );
    }
    $('#dataset_transfer_submit').data('publishing', false);
    $('#dataset_transfer_submit').prop('disabled', false);
}


function check_user_has_api_token(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200){            
            if(req.responseText === "True"){                
                // GoToStep2();
                $('#publish_destination_selection').hide();
                $('#publish_step1').hide();
                $('#publish_step2').show();
                $('#dataset_transfer_next_btn').attr("step", "3");
            }
            else{                
                $('#api_token_not_exist_alert_box').show();
            }            
        }
    }
    req.open("GET", dest_url);
    req.send();
}


function check_user_has_api_token_and_show_message(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            if(req.responseText === "True"){                
                $('#api_token_exist_info_box').show();
            }         
        }
    }
    req.open("GET", dest_url);
    req.send();
}


function add_csrf_token(formdata){
    let field_name = $('meta[name="csrf_field_name"]').attr('content') || '_csrf_token';
    let token = $('meta[name="' + field_name + '"]').attr('content');
    if(token){
        formdata.set(field_name, token);
        console.debug("Dataset transfer CSRF token attached", field_name);
    }
    else{
        console.error("Dataset transfer CSRF metadata is missing", field_name);
    }
}




function GoToStep2(){
    let dest_url = $('#org_list_call').val();
    let formdata = new FormData();
    formdata.set('package_id', $('#package_id').val());
    formdata.set('api_token', $("#transfer_api_token_input").val());
    formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
    add_csrf_token(formdata);
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {
            let orgList = JSON.parse(this.responseText);            
            if(orgList.length === 0){
                $('.org_should_exist').hide();
                $('#no_org_message').show();
            }
            else{
                $('#no_org_message').hide();                
                $('#dataset_transfer_org_list').select2({
                    data:orgList,
                    width:'50%'
                });                
            }
            $('#publish_step1').hide();
            $('#publish_step2').show();
        }
    }
    req.open("POST", dest_url);
    req.send(formdata);
}
