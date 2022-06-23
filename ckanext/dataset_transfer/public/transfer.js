$(document).ready(function(){ 
    
    /**
     * Click on the nect button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let dest_url = $('#org_list_call').val();
        let formdata = new FormData();
        formdata.set('package_id', $('#package_id').val());
        formdata.set('api_token', $("#transfer_api_token_input").val());
        let req = new XMLHttpRequest();
        req.onreadystatechange = function() {
            if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
                $('#dataset_transfer_org_list').select2({
                    data:JSON.parse(this.responseText),
                    width:'50%'
               });
               $('#transfer_api_token_warpper').hide();
               $('#transfer_org_selection').show();
            }
        }
        req.open("POST", dest_url);
        req.send(formdata);
    });

    
    
    
    
   


});